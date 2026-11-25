#!/usr/bin/env python3
"""
Lunar base battery pack + RTG thermal sizing (heat-only RTG).

Physics-first sizing: all inputs from YAML with owner/source metadata.
Luke chooses design numbers; cited-example values are labeled in reports.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml

SIGMA_DEFAULT = 5.670374419e-8


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def param_value(cfg: Dict[str, Any], *keys: str) -> Any:
    """Navigate nested dict and return `value` field from a parameter leaf."""
    node: Any = cfg
    for k in keys:
        node = node[k]
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def param_meta(cfg: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    node: Any = cfg
    for k in keys:
        node = node[k]
    if isinstance(node, dict) and "value" in node:
        return {
            "value": node.get("value"),
            "units": node.get("units", ""),
            "source": node.get("source", ""),
            "owner": node.get("owner", ""),
        }
    return {"value": node, "units": "", "source": "", "owner": ""}


def flatten_inputs(cfg: Dict[str, Any], prefix: str = "") -> List[Dict[str, str]]:
    """Collect parameter leaves for reporting."""
    rows: List[Dict[str, str]] = []
    for key, val in cfg.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            if "value" in val and "owner" in val:
                v = val["value"]
                if isinstance(v, list):
                    v_str = ", ".join(str(x) for x in v)
                elif v is None:
                    v_str = "(unset)"
                else:
                    v_str = str(v)
                rows.append(
                    {
                        "path": path,
                        "value": v_str,
                        "units": str(val.get("units", "")),
                        "source": str(val.get("source", "")),
                        "owner": str(val.get("owner", "")),
                    }
                )
            else:
                rows.extend(flatten_inputs(val, path))
    return rows


@dataclass
class BatterySizing:
    p_load_w: float
    p_heater_w: float
    t_dark_s: float
    dod: float
    eta: float
    specific_energy_wh_kg: float
    packaging_factor: float
    e_night_wh: float
    capacity_wh: float
    mass_kg: float
    n_series: int
    n_parallel: Optional[int]
    energy_per_string_wh: Optional[float]
    bus_v: float
    cell_v: float
    cell_ah: Optional[float]


def compute_night_energy_wh(p_load_w: float, p_heater_w: float, t_dark_h: float) -> float:
    """E_night = (P_load + P_heater) * t_dark (hours -> Wh)."""
    return (p_load_w + p_heater_w) * t_dark_h


def compute_required_capacity_wh(e_night_wh: float, dod: float, eta: float) -> float:
    """C = E_night / (DoD * eta)."""
    if dod <= 0 or eta <= 0:
        raise ValueError("DoD and eta must be positive")
    return e_night_wh / (dod * eta)


def compute_pack_mass_kg(capacity_wh: float, specific_energy_wh_kg: float, packaging_factor: float) -> float:
    """Mass = (capacity in Wh) / (Wh/kg) * packaging factor."""
    if specific_energy_wh_kg <= 0:
        raise ValueError("specific_energy must be positive")
    return (capacity_wh / specific_energy_wh_kg) * packaging_factor


def compute_series_count(bus_v: float, cell_v_nominal: float) -> int:
    return max(1, math.ceil(bus_v / cell_v_nominal))


def compute_parallel_strings(
    capacity_wh: float, n_series: int, cell_v: float, cell_ah: Optional[float]
) -> Tuple[Optional[int], Optional[float]]:
    """Energy per series string and parallel count if cell Ah is set."""
    if cell_ah is None or cell_ah <= 0:
        return None, None
    energy_per_string_wh = n_series * cell_v * cell_ah
    if energy_per_string_wh <= 0:
        return None, None
    n_parallel = max(1, math.ceil(capacity_wh / energy_per_string_wh))
    return n_parallel, energy_per_string_wh


def size_battery_pack(
    p_load_w: float,
    p_heater_w: float,
    t_dark_h: float,
    dod: float,
    eta: float,
    specific_energy_wh_kg: float,
    packaging_factor: float,
    bus_v: float,
    cell_v: float,
    cell_ah: Optional[float],
) -> BatterySizing:
    e_night = compute_night_energy_wh(p_load_w, p_heater_w, t_dark_h)
    capacity = compute_required_capacity_wh(e_night, dod, eta)
    mass = compute_pack_mass_kg(capacity, specific_energy_wh_kg, packaging_factor)
    n_series = compute_series_count(bus_v, cell_v)
    n_par, e_str = compute_parallel_strings(capacity, n_series, cell_v, cell_ah)
    return BatterySizing(
        p_load_w=p_load_w,
        p_heater_w=p_heater_w,
        t_dark_s=t_dark_h * 3600,
        dod=dod,
        eta=eta,
        specific_energy_wh_kg=specific_energy_wh_kg,
        packaging_factor=packaging_factor,
        e_night_wh=e_night,
        capacity_wh=capacity,
        mass_kg=mass,
        n_series=n_series,
        n_parallel=n_par,
        energy_per_string_wh=e_str,
        bus_v=bus_v,
        cell_v=cell_v,
        cell_ah=cell_ah,
    )


@dataclass
class ThermalLoss:
    q_rad_w: float
    q_leg_w: float
    q_passthrough_w: float
    q_total_w: float
    area_radiating_m2: float
    t_box_k: float
    t_sky_k: float
    t_ground_k: float
    emittance: float


def regolith_spreading_resistance_k_per_w(
    footpad_area_m2: float, k_regolith_w_mk: float
) -> float:
    """
    Spreading resistance for a circular contact patch on semi-infinite regolith.

    R ≈ 1 / (2 * k * sqrt(A))  (order-of-magnitude half-space; cited-example form).
    """
    if footpad_area_m2 <= 0 or k_regolith_w_mk <= 0:
        return float("inf")
    return 1.0 / (2.0 * k_regolith_w_mk * math.sqrt(footpad_area_m2))


def leg_conduction_w(
    n_legs: int,
    k_leg: float,
    a_cross: float,
    length_m: float,
    t_box_k: float,
    t_surface_k: float,
    footpad_area: float,
    h_contact: float,
    k_regolith: float,
) -> float:
    """
    Leg + footpad + regolith in series from T_box to lunar night surface (Colozza-style).
    Q = (T_box - T_surface) / R_total, distributed over n_legs paths in parallel.
    """
    if n_legs <= 0 or length_m <= 0:
        return 0.0
    r_leg = length_m / (k_leg * a_cross) if a_cross > 0 and k_leg > 0 else float("inf")
    r_contact = 1.0 / (h_contact * footpad_area) if h_contact > 0 and footpad_area > 0 else float("inf")
    r_regolith = regolith_spreading_resistance_k_per_w(footpad_area, k_regolith)
    r_path = r_leg + r_contact + r_regolith
    if not math.isfinite(r_path) or r_path <= 0:
        return 0.0
    # n_legs identical paths in parallel
    r_total = r_path / n_legs
    return max(0.0, (t_box_k - t_surface_k) / r_total)


def ring_radiating_area_m2(
    n_boxes: int,
    length_m: float,
    width_m: float,
    height_m: float,
    ring_radius_m: float,
    top_area_fraction_sky: float,
) -> float:
    """
    Circular ring of identical boxes: each box contributes outward vertical face,
    inward vertical face (still radiates to environment), and top face to sky.

    Outer arc length per box ≈ (2*pi*R)/n * H for outward face;
    we use full box vertical perimeter exposure minus shared seams (simplified).
    """
    if n_boxes <= 0:
        return 0.0
    arc_per_box = (2.0 * math.pi * ring_radius_m) / n_boxes
    # Outward face: arc * height
    a_out = n_boxes * arc_per_box * height_m
    # Inward face toward lander/RTG (still loses heat)
    a_in = n_boxes * width_m * height_m
    # Top faces
    a_top = n_boxes * length_m * width_m * top_area_fraction_sky
    # Ends (thin): two per box
    a_ends = n_boxes * 2.0 * width_m * height_m * 0.5  # half counted as interior coupling
    return a_out + a_in + a_top + a_ends


def radiation_loss_w(
    emittance: float,
    area_m2: float,
    t_box_k: float,
    t_sky_k: float,
    t_ground_k: float,
    f_sky: float,
    f_ground: float,
    sigma: float = SIGMA_DEFAULT,
) -> float:
    """Q_rad = e*sigma*A*(Fs*(T^4-Tsky^4) + Fg*(T^4-Tg^4))."""
    if area_m2 <= 0:
        return 0.0
    fs = f_sky
    fg = f_ground
    # normalize if user sums != 1
    s = fs + fg
    if s > 0:
        fs, fg = fs / s, fg / s
    t4 = t_box_k**4
    q = emittance * sigma * area_m2 * (
        fs * (t4 - t_sky_k**4) + fg * (t4 - t_ground_k**4)
    )
    return max(0.0, q)


def compute_thermal_loss(
    t_box_k: float,
    t_sky_k: float,
    t_ground_k: float,
    emittance: float,
    n_boxes: int,
    box_l: float,
    box_w: float,
    box_h: float,
    ring_r: float,
    f_sky: float,
    f_ground: float,
    top_sky_frac: float,
    n_legs: int,
    k_leg: float,
    a_cross: float,
    leg_len: float,
    footpad_a: float,
    h_contact: float,
    k_regolith: float,
    passthrough_w: float,
    sigma: float = SIGMA_DEFAULT,
) -> ThermalLoss:
    area = ring_radiating_area_m2(n_boxes, box_l, box_w, box_h, ring_r, top_sky_frac)
    q_rad = radiation_loss_w(emittance, area, t_box_k, t_sky_k, t_ground_k, f_sky, f_ground, sigma)
    q_leg = leg_conduction_w(
        n_legs, k_leg, a_cross, leg_len, t_box_k, t_ground_k, footpad_a, h_contact, k_regolith
    )
    q_total = q_rad + q_leg + passthrough_w
    return ThermalLoss(
        q_rad_w=q_rad,
        q_leg_w=q_leg,
        q_passthrough_w=passthrough_w,
        q_total_w=q_total,
        area_radiating_m2=area,
        t_box_k=t_box_k,
        t_sky_k=t_sky_k,
        t_ground_k=t_ground_k,
        emittance=emittance,
    )


def required_rtg_thermal_w(q_loss_w: float, coupling: float) -> float:
    """Q_RTG = Q_loss / coupling (thermal output only, no electric)."""
    if coupling <= 0:
        raise ValueError("coupling must be positive")
    return q_loss_w / coupling


def heater_shortfall_w(q_loss_w: float, coupling: float, q_rtg_given_w: float) -> float:
    """Electric heater power if fixed RTG thermal output is below requirement."""
    delivered = coupling * q_rtg_given_w
    return max(0.0, q_loss_w - delivered)


@dataclass
class CaseResult:
    load_name: str
    load_w: float
    specific_energy_wh_kg: float
    battery: BatterySizing
    thermal: ThermalLoss
    q_rtg_total_w: float
    q_rtg_per_unit_w: Dict[int, float]
    mode: str
    iterations: int


def solve_case(
    load_name: str,
    load_w: float,
    specific_energy: float,
    cfg: Dict[str, Any],
    emittance: Optional[float] = None,
    k_leg: Optional[float] = None,
    max_iter: int = 20,
    tol_w: float = 1e-3,
) -> CaseResult:
    mode = param_value(cfg, "meta", "mode") or "solve_rtg"
    t_dark = param_value(cfg, "night", "t_dark_h")
    dod = param_value(cfg, "battery", "depth_of_discharge")
    eta = param_value(cfg, "battery", "round_trip_efficiency")
    packaging = param_value(cfg, "battery", "packaging_insulation_mass_factor")
    bus_v = param_value(cfg, "battery", "bus_voltage_v")
    cell_v = param_value(cfg, "battery", "cell_nominal_voltage_v")
    cell_ah = param_value(cfg, "battery", "cell_capacity_ah")
    t_box = param_value(cfg, "battery", "box_target_temperature_k")
    t_sky = param_value(cfg, "thermal_environment", "deep_space_sink_k")
    t_ground = param_value(cfg, "thermal_environment", "night_surface_k")
    k_reg = param_value(cfg, "thermal_environment", "regolith_thermal_conductivity_w_per_mk")
    h_contact = param_value(cfg, "thermal_environment", "footpad_contact_conductance_w_per_m2k")

    e_eff = emittance if emittance is not None else param_value(cfg, "radiation", "emittance_default")
    sigma = param_value(cfg, "physics", "stefan_boltzmann_w_per_m2k4") or SIGMA_DEFAULT

    n_boxes = param_value(cfg, "geometry", "n_battery_boxes")
    box_l = param_value(cfg, "geometry", "box_length_m")
    box_w = param_value(cfg, "geometry", "box_width_m")
    box_h = param_value(cfg, "geometry", "box_height_m")
    ring_r = param_value(cfg, "geometry", "ring_radius_m")
    f_sky = param_value(cfg, "geometry", "view_factor_sky")
    f_ground = param_value(cfg, "geometry", "view_factor_ground")
    top_frac = param_value(cfg, "geometry", "top_area_fraction_sky")

    n_legs = param_value(cfg, "lander_legs", "n_legs")
    k_leg_val = k_leg if k_leg is not None else param_value(cfg, "lander_legs", "leg_thermal_conductivity_w_per_mk")
    a_cross = param_value(cfg, "lander_legs", "leg_cross_section_m2")
    leg_len = param_value(cfg, "lander_legs", "leg_length_m")
    footpad_a = param_value(cfg, "lander_legs", "footpad_area_m2")

    passthrough = param_value(cfg, "losses", "passthrough_w")
    coupling = param_value(cfg, "losses", "rtg_to_battery_coupling")
    rtg_counts: List[int] = param_value(cfg, "rtg", "count_list")
    q_rtg_fixed = param_value(cfg, "rtg", "thermal_output_w")

    p_heater = 0.0
    iterations = 0
    # Fixed geometry: one battery/thermal pass unless fixed_rtg creates heater load feedback.
    for _ in range(max_iter):
        iterations += 1
        battery = size_battery_pack(
            load_w, p_heater, t_dark, dod, eta, specific_energy, packaging, bus_v, cell_v, cell_ah
        )
        thermal = compute_thermal_loss(
            t_box,
            t_sky,
            t_ground,
            e_eff,
            n_boxes,
            box_l,
            box_w,
            box_h,
            ring_r,
            f_sky,
            f_ground,
            top_frac,
            n_legs,
            k_leg_val,
            a_cross,
            leg_len,
            footpad_a,
            h_contact,
            k_reg,
            passthrough,
            sigma,
        )
        if mode == "fixed_rtg" and q_rtg_fixed is not None:
            new_heater = heater_shortfall_w(thermal.q_total_w, coupling, float(q_rtg_fixed))
            if abs(new_heater - p_heater) < tol_w:
                p_heater = new_heater
                break
            p_heater = new_heater
        else:
            p_heater = 0.0
            break

    if mode == "fixed_rtg" and q_rtg_fixed is not None:
        q_rtg_total = float(q_rtg_fixed)
    else:
        q_rtg_total = required_rtg_thermal_w(thermal.q_total_w, coupling)

    per_unit = {n: q_rtg_total / n for n in rtg_counts if n > 0}

    return CaseResult(
        load_name=load_name,
        load_w=load_w,
        specific_energy_wh_kg=specific_energy,
        battery=battery,
        thermal=thermal,
        q_rtg_total_w=q_rtg_total,
        q_rtg_per_unit_w=per_unit,
        mode=mode,
        iterations=iterations,
    )


def todo_luke_list(cfg: Dict[str, Any]) -> List[str]:
    todos = []
    for row in flatten_inputs(cfg):
        if row["owner"] == "TODO-luke":
            todos.append(f"{row['path']}: {row['value']} {row['units']} — {row['source']}")
    return todos


def format_results_table(results: List[CaseResult]) -> str:
    lines = [
        "",
        "=" * 100,
        "LUNAR BASE BATTERY + RTG THERMAL SIZER",
        "=" * 100,
    ]
    for r in results:
        lines.append(f"\n--- {r.load_name} @ {r.specific_energy_wh_kg} Wh/kg (mode={r.mode}, iter={r.iterations}) ---")
        b = r.battery
        lines.append(f"  P_load        = {b.p_load_w:.1f} W")
        lines.append(f"  P_heater      = {b.p_heater_w:.1f} W")
        lines.append(f"  E_night       = {b.e_night_wh/1000:.3f} kWh")
        lines.append(f"  Capacity C    = {b.capacity_wh/1000:.3f} kWh")
        lines.append(f"  Pack mass     = {b.mass_kg:.1f} kg")
        lines.append(f"  N_series      = {b.n_series} @ {b.bus_v} V bus / {b.cell_v} V cell")
        if b.n_parallel is None:
            lines.append("  Parallel strings: (cell Ah unset — pack-level sizing only)")
        else:
            lines.append(f"  N_parallel    = {b.n_parallel} (≈{b.energy_per_string_wh:.0f} Wh/string)")
        lines.append(f"  Q_loss total  = {r.thermal.q_total_w:.1f} W (rad {r.thermal.q_rad_w:.1f}, leg {r.thermal.q_leg_w:.1f})")
        lines.append(f"  Q_RTG total   = {r.q_rtg_total_w:.1f} W thermal (heat only)")
        for n, q in sorted(r.q_rtg_per_unit_w.items()):
            lines.append(f"    per RTG if n={n}: {q:.1f} W")
    return "\n".join(lines)


def run_sensitivity(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Q_RTG and mass vs e_eff, leg material, specific energy, load case."""
    loads = [
        ("primary", param_value(cfg, "loads", "primary_w")),
        ("survival_high", param_value(cfg, "loads", "survival_high_w")),
        ("survival_low", param_value(cfg, "loads", "survival_low_w")),
    ]
    se_low = param_value(cfg, "battery", "specific_energy_wh_per_kg_low")
    se_high = param_value(cfg, "battery", "specific_energy_wh_per_kg_high")
    em_list = cfg.get("radiation", {}).get("emittance_sensitivity", [])
    leg_list = cfg.get("lander_legs", {}).get("leg_material_sensitivity", [])

    rows: List[Dict[str, Any]] = []
    for load_name, load_w in loads:
        for se in (se_low, se_high):
            for em_entry in em_list:
                em = em_entry["value"]
                em_label = em_entry.get("label", str(em))
                r = solve_case(load_name, load_w, se, cfg, emittance=em)
                rows.append(
                    {
                        "load": load_name,
                        "specific_energy_wh_kg": se,
                        "emittance": em,
                        "emittance_label": em_label,
                        "leg_material": "default",
                        "mass_kg": r.battery.mass_kg,
                        "q_rtg_w": r.q_rtg_total_w,
                    }
                )
            for leg in leg_list:
                r = solve_case(
                    load_name,
                    load_w,
                    se,
                    cfg,
                    k_leg=leg["k_w_per_mk"],
                )
                rows.append(
                    {
                        "load": load_name,
                        "specific_energy_wh_kg": se,
                        "emittance": param_value(cfg, "radiation", "emittance_default"),
                        "emittance_label": "default",
                        "leg_material": leg["name"],
                        "mass_kg": r.battery.mass_kg,
                        "q_rtg_w": r.q_rtg_total_w,
                    }
                )
    return rows


def default_result_set(cfg: Dict[str, Any]) -> List[CaseResult]:
    """Primary analysis matrix: loads × specific energy range."""
    se_low = param_value(cfg, "battery", "specific_energy_wh_per_kg_low")
    se_high = param_value(cfg, "battery", "specific_energy_wh_per_kg_high")
    loads = [
        ("primary_5000W", param_value(cfg, "loads", "primary_w")),
        ("survival_100W", param_value(cfg, "loads", "survival_high_w")),
        ("survival_50W", param_value(cfg, "loads", "survival_low_w")),
    ]
    results: List[CaseResult] = []
    for name, pw in loads:
        for se in (se_low, se_high):
            results.append(solve_case(name, pw, se, cfg))
    return results


def write_report_pdf(
    path: Path,
    cfg: Dict[str, Any],
    results: List[CaseResult],
    sensitivity: List[Dict[str, Any]],
    todos: List[str],
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    input_rows = flatten_inputs(cfg)

    with PdfPages(path) as pdf:
        # Page 1: title + inputs (abbreviated)
        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.axis("off")
        title = param_meta(cfg, "meta", "title").get("value", "Lunar Base Sizer")
        ax.text(0.05, 0.98, title, fontsize=14, fontweight="bold", va="top")
        ax.text(
            0.05,
            0.94,
            "AI-assisted code (Cursor cloud agent, directed by Luke via Grok Bot);\n"
            "research from cited sources via AI research assistant.",
            fontsize=8,
            va="top",
        )
        y = 0.88
        ax.text(0.05, y, "Inputs (owner / source)", fontsize=11, fontweight="bold")
        y -= 0.03
        for row in input_rows[:45]:
            line = f"{row['path']}: {row['value']} {row['units']} [{row['owner']}]"
            ax.text(0.05, y, line[:95], fontsize=6, family="monospace")
            y -= 0.018
            if y < 0.05:
                break
        pdf.savefig(fig)
        plt.close(fig)

        # Page 2: results
        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.axis("off")
        y = 0.98
        ax.text(0.05, y, "Sizing results", fontsize=12, fontweight="bold")
        y -= 0.04
        for r in results:
            b = r.battery
            block = (
                f"{r.load_name} @ {r.specific_energy_wh_kg} Wh/kg\n"
                f"  E_night={b.e_night_wh/1000:.2f} kWh  C={b.capacity_wh/1000:.2f} kWh  mass={b.mass_kg:.0f} kg\n"
                f"  Q_loss={r.thermal.q_total_w:.0f} W  Q_RTG={r.q_rtg_total_w:.0f} W\n"
                f"  RTG/unit: "
                + ", ".join(f"n{n}={q:.0f}W" for n, q in sorted(r.q_rtg_per_unit_w.items()))
            )
            ax.text(0.05, y, block, fontsize=8, va="top", family="monospace")
            y -= 0.12
        lipo_lim = param_value(cfg, "battery", "lipo_cold_limit_k")
        t_box = param_value(cfg, "battery", "box_target_temperature_k")
        ax.text(
            0.05,
            0.08,
            f"Battery box held at {t_box:.2f} K (check: above LiPo limit {lipo_lim} K).",
            fontsize=9,
        )
        pdf.savefig(fig)
        plt.close(fig)

        # Page 3: sensitivity + TODO
        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.axis("off")
        ax.text(0.05, 0.98, "Sensitivity (subset)", fontsize=12, fontweight="bold")
        y = 0.94
        for row in sensitivity[:35]:
            line = (
                f"{row['load']} se={row['specific_energy_wh_kg']} "
                f"e={row.get('emittance_label', row['emittance'])} "
                f"leg={row['leg_material']}: mass={row['mass_kg']:.0f}kg Q_RTG={row['q_rtg_w']:.0f}W"
            )
            ax.text(0.05, y, line[:100], fontsize=6, family="monospace")
            y -= 0.022
        ax.text(0.05, max(0.35, y), "Values Luke still needs to choose (TODO-luke):", fontsize=10, fontweight="bold")
        y2 = max(0.32, y - 0.03)
        for t in todos:
            ax.text(0.05, y2, f"• {t[:90]}", fontsize=7)
            y2 -= 0.022
        ax.text(
            0.05,
            0.04,
            "Items marked cited-example are examples, not Luke's final design.",
            fontsize=8,
            style="italic",
        )
        pdf.savefig(fig)
        plt.close(fig)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Lunar base battery + RTG thermal sizer")
    parser.add_argument("config", type=Path, help="Path to config.yaml")
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="PDF output path (default from config output.report_pdf)",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    results = default_result_set(cfg)
    sensitivity = run_sensitivity(cfg)
    todos = todo_luke_list(cfg)

    print(format_results_table(results))
    print("\n--- TODO-luke ---")
    for t in todos:
        print(f"  • {t}")

    pdf_path = args.pdf or Path(param_value(cfg, "output", "report_pdf") or "report.pdf")
    write_report_pdf(pdf_path, cfg, results, sensitivity, todos)
    print(f"\nWrote {pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())