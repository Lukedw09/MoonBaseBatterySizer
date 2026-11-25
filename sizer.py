#!/usr/bin/env python3
"""
Lunar base battery pack + RTG thermal sizing (heat-only RTG).
All inputs from YAML; Luke-owned vs cited-example vs TODO-luke are labeled.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

SIGMA_DEFAULT = 5.670374419e-8

# Paths that must be set (value not null) before a full sizing run.
DESIGN_PATHS = [
    ("geometry", "n_battery_boxes"),
    ("geometry", "box_length_m"),
    ("geometry", "box_width_m"),
    ("geometry", "box_height_m"),
    ("geometry", "ring_radius_m"),
    ("geometry", "bottom_radiates_to"),
    ("lander_legs", "leg_cross_section_m2"),
    ("lander_legs", "leg_length_m"),
    ("lander_legs", "leg_surface_emissivity"),
    ("lander_legs", "footpad_area_m2"),
    ("battery", "packaging_insulation_mass_factor"),
    ("battery", "cell_nominal_voltage_v"),
    ("losses", "passthrough_w"),
    ("rtg", "coupling_fraction"),
    ("rtg", "heat_path"),
    ("battery", "eta_definition"),
    ("lander_legs", "leg_perimeter_m"),
]

# TODO-luke fields that may stay null (still listed in report for Luke).
NON_BLOCKING_TODO_PATHS = {
    "battery.cell_capacity_ah",
    "battery.capacity_derating_factor_at_0c",
    "battery.minimum_charge_temperature_k",
    "battery.pack_specific_heat_j_per_kgk",
    "battery.dawn_warm_up_h",
    "thermal_environment.lander_deck_temperature_k",
    "fallback.mode",
    "rtg.thermal_output_w",
    "radiation.penetration_seam_emittance_multiplier",
    "rtg.inward_face_absorptance",
    "fallback.pack_volumetric_energy_density_wh_per_m3",
}


class DesignInputError(Exception):
    """Luke must choose required design inputs."""

    def __init__(self, missing: List[str]):
        self.missing = missing
        super().__init__("Luke needs to choose: " + "; ".join(missing))


class ConfigError(Exception):
    pass


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def param_value(cfg: Dict[str, Any], *keys: str) -> Any:
    node: Any = cfg
    for k in keys:
        node = node[k]
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def param_owner(cfg: Dict[str, Any], *keys: str) -> str:
    node: Any = cfg
    for k in keys:
        node = node[k]
    if isinstance(node, dict):
        return str(node.get("owner", ""))
    return ""


def flatten_inputs(cfg: Dict[str, Any], prefix: str = "") -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for key, val in cfg.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            if "value" in val and "owner" in val:
                v = val["value"]
                v_str = "(unset)" if v is None else (", ".join(str(x) for x in v) if isinstance(v, list) else str(v))
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


def blocking_missing(cfg: Dict[str, Any]) -> List[str]:
    """Design inputs that must be non-null before running."""
    missing: List[str] = []
    mode = param_value(cfg, "meta", "mode")
    for path in DESIGN_PATHS:
        if param_value(cfg, *path) is None:
            missing.append(".".join(path))
    design_dotted = {".".join(p) for p in DESIGN_PATHS}
    for row in flatten_inputs(cfg):
        if row["owner"] != "TODO-luke" or row["value"] != "(unset)":
            continue
        if row["path"] in NON_BLOCKING_TODO_PATHS or row["path"] in design_dotted:
            continue
        if row["path"] == "rtg.thermal_output_w" and mode != "fixed_rtg":
            continue
        missing.append(f"{row['path']} ({row['source']})")
    return sorted(set(missing))


def missing_luke_choices(cfg: Dict[str, Any]) -> List[str]:
    """Complete TODO-luke list for reports (includes optional unset fields)."""
    todos: List[str] = []
    for row in flatten_inputs(cfg):
        if row["owner"] == "TODO-luke":
            suffix = " (unset)" if row["value"] == "(unset)" else ""
            todos.append(f"{row['path']}: {row['value']} {row['units']} — {row['source']}{suffix}")
    return todos


def validate_for_run(cfg: Dict[str, Any], allow_incomplete: bool = False) -> None:
    mode = param_value(cfg, "meta", "mode")
    if mode == "fixed_rtg" and param_value(cfg, "rtg", "thermal_output_w") is None:
        raise ConfigError("mode=fixed_rtg requires rtg.thermal_output_w to be set (not null).")
    n_boxes = param_value(cfg, "geometry", "n_battery_boxes")
    if n_boxes is not None and n_boxes <= 0:
        raise ConfigError("geometry.n_battery_boxes must be positive.")
    n_legs = param_value(cfg, "lander_legs", "n_legs")
    if n_legs is not None and n_legs <= 0:
        raise ConfigError("lander_legs.n_legs must be positive.")
    coupling = param_value(cfg, "rtg", "coupling_fraction")
    if coupling is not None and coupling <= 0:
        raise ConfigError("rtg.coupling_fraction must be positive when set.")
    missing = blocking_missing(cfg)
    if missing and not allow_incomplete:
        raise DesignInputError(missing)


def battery_efficiency_value(cfg: Dict[str, Any]) -> float:
    bat = cfg.get("battery", {})
    if "efficiency" in bat:
        return float(param_value(cfg, "battery", "efficiency"))
    if "round_trip_efficiency" in bat:
        return float(param_value(cfg, "battery", "round_trip_efficiency"))
    raise ConfigError("battery.efficiency must be set in config.yaml")


def discharge_efficiency_for_sizing(eta: float, eta_definition: str) -> float:
    """Pack sizing uses discharge-side efficiency only (requires eta_definition)."""
    if eta_definition == "round_trip":
        return math.sqrt(eta)
    if eta_definition == "discharge":
        return eta
    raise ConfigError(f"Unknown eta_definition: {eta_definition}")


def internal_waste_heat_w(p_load_w: float, eta: float) -> Dict[str, float]:
    """Always compute both interpretations for display; active one chosen via eta_definition."""
    return {
        "round_trip_definition": p_load_w * (1.0 / math.sqrt(eta) - 1.0),
        "discharge_definition": p_load_w * (1.0 / eta - 1.0),
    }


def pick_internal_heat(q_map: Dict[str, float], eta_definition: str) -> Tuple[float, str]:
    if eta_definition == "round_trip":
        return q_map["round_trip_definition"], "round_trip"
    if eta_definition == "discharge":
        return q_map["discharge_definition"], "discharge"
    raise ConfigError("eta_definition must be round_trip or discharge")


def compute_night_energy_wh(p_load_w: float, p_heater_w: float, t_dark_h: float) -> float:
    return (p_load_w + p_heater_w) * t_dark_h


def compute_required_capacity_wh(e_night_wh: float, dod: float, eta_discharge: float) -> float:
    if dod <= 0 or eta_discharge <= 0:
        raise ValueError("DoD and discharge eta must be positive")
    return e_night_wh / (dod * eta_discharge)


def compute_pack_mass_kg(capacity_wh: float, specific_energy_wh_kg: float, packaging_factor: float) -> float:
    if specific_energy_wh_kg <= 0:
        raise ValueError("specific_energy must be positive")
    return (capacity_wh / specific_energy_wh_kg) * packaging_factor


def compute_series_count(bus_v: float, cell_v_nominal: float) -> int:
    if cell_v_nominal is None or cell_v_nominal <= 0:
        raise ConfigError("cell_nominal_voltage_v must be set and positive.")
    return max(1, math.ceil(bus_v / cell_v_nominal))


def compute_parallel_strings(
    capacity_wh: float, n_series: int, cell_v: float, cell_ah: Optional[float]
) -> Tuple[Optional[int], Optional[float]]:
    if cell_ah is None or cell_ah <= 0:
        return None, None
    energy_per_string_wh = n_series * cell_v * cell_ah
    if energy_per_string_wh <= 0:
        return None, None
    return max(1, math.ceil(capacity_wh / energy_per_string_wh)), energy_per_string_wh


@dataclass
class BatterySizing:
    p_load_w: float
    p_heater_w: float
    t_dark_h: float
    dod: float
    eta_discharge: float
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


def size_battery_pack(
    p_load_w: float,
    p_heater_w: float,
    t_dark_h: float,
    dod: float,
    eta_discharge: float,
    specific_energy_wh_kg: float,
    packaging_factor: float,
    bus_v: float,
    cell_v: float,
    cell_ah: Optional[float],
) -> BatterySizing:
    e_night = compute_night_energy_wh(p_load_w, p_heater_w, t_dark_h)
    capacity = compute_required_capacity_wh(e_night, dod, eta_discharge)
    mass = compute_pack_mass_kg(capacity, specific_energy_wh_kg, packaging_factor)
    n_series = compute_series_count(bus_v, cell_v)
    n_par, e_str = compute_parallel_strings(capacity, n_series, cell_v, cell_ah)
    return BatterySizing(
        p_load_w=p_load_w,
        p_heater_w=p_heater_w,
        t_dark_h=t_dark_h,
        dod=dod,
        eta_discharge=eta_discharge,
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


def end_face_exposure_factor(n_boxes: int, ring_radius_m: float, box_length_m: float, box_width_m: float) -> float:
    """Reduce end-face area when tangential gap < box width."""
    if n_boxes <= 0 or ring_radius_m <= 0:
        return 1.0
    arc = (2.0 * math.pi * ring_radius_m) / n_boxes
    gap = arc - box_length_m
    if gap >= box_width_m:
        return 1.0
    return max(0.0, gap / box_width_m) if box_width_m > 0 else 0.0


def per_box_face_areas_m2(
    length_m: float, width_m: float, height_m: float, end_factor: float
) -> Dict[str, float]:
    """Outer/inner vertical L×H, ends 2×W×H, top/bottom L×W."""
    return {
        "outer_vertical": length_m * height_m,
        "inner_vertical": length_m * height_m,
        "ends": 2.0 * width_m * height_m * end_factor,
        "top": length_m * width_m,
        "bottom": length_m * width_m,
    }


def total_ring_radiating_area_m2(
    n_boxes: int,
    length_m: float,
    width_m: float,
    height_m: float,
    ring_radius_m: float,
) -> Tuple[float, Dict[str, float]]:
    ef = end_face_exposure_factor(n_boxes, ring_radius_m, length_m, width_m)
    per = per_box_face_areas_m2(length_m, width_m, height_m, ef)
    totals = {k: v * n_boxes for k, v in per.items()}
    total = sum(totals.values())
    return total, totals


def face_radiation_w(
    emittance: float,
    area_m2: float,
    t_box_k: float,
    t_sky_k: float,
    t_ground_k: float,
    f_sky: float,
    f_ground: float,
    sigma: float,
) -> float:
    if area_m2 <= 0:
        return 0.0
    s = f_sky + f_ground
    if s <= 0:
        return 0.0
    fs, fg = f_sky / s, f_ground / s
    t4 = t_box_k**4
    q = emittance * sigma * area_m2 * (fs * (t4 - t_sky_k**4) + fg * (t4 - t_ground_k**4))
    return max(0.0, q)


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
    return face_radiation_w(emittance, area_m2, t_box_k, t_sky_k, t_ground_k, f_sky, f_ground, sigma)


def box_radiation_loss_w(
    n_boxes: int,
    length_m: float,
    width_m: float,
    height_m: float,
    ring_radius_m: float,
    emittance: float,
    t_box_k: float,
    t_sky_k: float,
    t_ground_k: float,
    t_deck_k: float,
    bottom_to: str,
    f_sky_vert: float,
    f_ground_vert: float,
    emittance_multiplier: float,
    sigma: float,
) -> Tuple[float, float, Dict[str, float]]:
    """Sum radiation by face type. Returns q_total, total_area, area_breakdown."""
    if n_boxes <= 0:
        raise ConfigError("geometry.n_battery_boxes must be positive for thermal sizing.")
    e_eff = emittance * emittance_multiplier
    _, areas = total_ring_radiating_area_m2(n_boxes, length_m, width_m, height_m, ring_radius_m)
    q = 0.0
    q += face_radiation_w(e_eff, areas["outer_vertical"], t_box_k, t_sky_k, t_ground_k, f_sky_vert, f_ground_vert, sigma)
    q += face_radiation_w(e_eff, areas["inner_vertical"], t_box_k, t_sky_k, t_ground_k, f_sky_vert, f_ground_vert, sigma)
    q += face_radiation_w(e_eff, areas["ends"], t_box_k, t_sky_k, t_ground_k, f_sky_vert, f_ground_vert, sigma)
    q += face_radiation_w(e_eff, areas["top"], t_box_k, t_sky_k, t_ground_k, 1.0, 0.0, sigma)
    t_bottom = t_ground_k if bottom_to == "ground" else t_deck_k
    q += face_radiation_w(e_eff, areas["bottom"], t_box_k, t_sky_k, t_bottom, 0.0, 1.0, sigma)
    total_a = sum(areas.values())
    return q, total_a, areas


def disk_radius_from_area(area_m2: float) -> float:
    return math.sqrt(area_m2 / math.pi)


def regolith_spreading_resistance_k_per_w(footpad_area_m2: float, k_regolith_w_mk: float) -> float:
    """
    Circular disk on semi-infinite half-space: R = 1/(4 k a).
    See Incropera conduction constriction / Carslaw & Jaeger.
    """
    if footpad_area_m2 <= 0 or k_regolith_w_mk <= 0:
        return float("inf")
    a = disk_radius_from_area(footpad_area_m2)
    return 1.0 / (4.0 * k_regolith_w_mk * a)


def leg_conduction_network_w(
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
    Standalone R-network reference (tests only — not added to fin loss).
    Full leg R in series: leg metal + contact + regolith spreading.
    """
    if n_legs <= 0:
        raise ConfigError("lander_legs.n_legs must be positive.")
    if length_m <= 0 or a_cross <= 0 or k_leg <= 0:
        return 0.0
    r_leg = length_m / (k_leg * a_cross)
    r_contact = 1.0 / (h_contact * footpad_area) if h_contact > 0 and footpad_area > 0 else float("inf")
    r_reg = regolith_spreading_resistance_k_per_w(footpad_area, k_regolith)
    r_path = r_leg + r_contact + r_reg
    if not math.isfinite(r_path) or r_path <= 0:
        return 0.0
    return max(0.0, n_legs * (t_box_k - t_surface_k) / r_path)


def foot_thermal_resistance_k_per_w(footpad_area: float, h_contact: float, k_regolith: float) -> float:
    r_contact = 1.0 / (h_contact * footpad_area) if h_contact > 0 and footpad_area > 0 else float("inf")
    r_reg = regolith_spreading_resistance_k_per_w(footpad_area, k_regolith)
    return r_contact + r_reg


def radiative_loss_per_length_w(T: float, perimeter_m: float, emissivity: float, t_sky: float, t_ground: float,
                              f_sky: float, f_ground: float, sigma: float) -> float:
    """Power lost per meter of leg length at temperature T (W/m)."""
    s = f_sky + f_ground
    fs = f_sky / s if s > 0 else 0.5
    fg = f_ground / s if s > 0 else 0.5
    t4 = T**4
    qd = fs * (t4 - t_sky**4) + fg * (t4 - t_ground**4)
    return max(0.0, emissivity * sigma * perimeter_m * qd)


def analytic_constant_h_fin_w(
    k_leg: float, a_cross: float, perimeter_m: float, length_m: float, t_root: float, t_inf: float, h_lin: float,
) -> float:
    """Incropera straight fin, insulated tip: Q = M*(Tb-Tinf)*tanh(mL), m=sqrt(hP/(kA))."""
    m = math.sqrt(h_lin * perimeter_m / (k_leg * a_cross))
    m_val = math.sqrt(h_lin * perimeter_m * k_leg * a_cross)
    return m_val * (t_root - t_inf) * math.tanh(m * length_m)


class FinSolverError(ConfigError):
    """Radiating / linear fin BVP did not converge."""


def _integrate_fin_heat_linear(
    x: "np.ndarray", T: "np.ndarray", h_lin: float, perimeter_m: float, t_inf: float, k_leg: float, a_cross: float
) -> float:
    import numpy as np

    ql = h_lin * perimeter_m * (T - t_inf)
    return float(np.trapezoid(ql, x))


def solve_linear_h_fin_bvp(
    k_leg: float,
    a_cross: float,
    perimeter_m: float,
    length_m: float,
    t_root: float,
    t_inf: float,
    h_lin: float,
    n_mesh: int,
    rtol: float = 1e-5,
    max_nodes: Optional[int] = None,
) -> Tuple[float, "np.ndarray", "np.ndarray"]:
    """Constant-h straight fin, adiabatic tip; returns Q, x, T."""
    import numpy as np
    from scipy.integrate import solve_bvp

    ka = k_leg * a_cross

    def fun(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        qlin = h_lin * perimeter_m * (y[0] - t_inf) / ka
        return np.vstack((y[1], qlin))

    def bc(ya: np.ndarray, yb: np.ndarray) -> np.ndarray:
        return np.array([ya[0] - t_root, yb[1]])

    x = np.linspace(0.0, length_m, max(3, n_mesh))
    tg = np.linspace(t_root, t_inf, len(x))
    y0 = np.vstack([tg, np.gradient(tg, x, edge_order=2)])
    node_cap = max_nodes if max_nodes is not None else max(5000, 4 * n_mesh)
    sol = solve_bvp(fun, bc, x, y0, tol=rtol, max_nodes=node_cap, verbose=0)
    if not sol.success:
        raise FinSolverError(f"Linear fin BVP failed: {sol.message}")
    x_f = sol.x
    T_f = sol.sol(x_f)[0]
    q = _integrate_fin_heat_linear(x_f, T_f, h_lin, perimeter_m, t_inf, k_leg, a_cross)
    return max(0.0, q), x_f, T_f


def bvp_constant_h_fin_w(
    k_leg: float, a_cross: float, perimeter_m: float, length_m: float, t_root: float, t_inf: float,
    h_lin: float, n_nodes: int,
) -> float:
    """Constant-h fin heat loss via BVP (initial mesh = n_nodes)."""
    q, _, _ = solve_linear_h_fin_bvp(k_leg, a_cross, perimeter_m, length_m, t_root, t_inf, h_lin, n_nodes)
    return q


def _integrate_radiative_heat(
    x: "np.ndarray",
    T: "np.ndarray",
    perimeter_m: float,
    emissivity: float,
    t_sky: float,
    t_ground: float,
    f_sky: float,
    f_ground: float,
    sigma: float,
) -> float:
    import numpy as np

    ql = np.array(
        [
            radiative_loss_per_length_w(float(Ti), perimeter_m, emissivity, t_sky, t_ground, f_sky, f_ground, sigma)
            for Ti in T
        ]
    )
    return float(np.trapezoid(ql, x))


def solve_radiating_leg_fin(
    k_leg: float,
    a_cross: float,
    perimeter_m: float,
    length_m: float,
    leg_emissivity: float,
    t_root_k: float,
    t_sky_k: float,
    t_ground_k: float,
    t_surf_k: float,
    f_sky: float,
    f_ground: float,
    footpad_area: float,
    h_contact: float,
    k_regolith: float,
    n_nodes: int,
    sigma: float,
    rtol: float = 1e-5,
    max_nodes: Optional[int] = None,
) -> Tuple[float, float, List[float]]:
    """Radiating leg: scipy BVP, fixed T_root, foot R_contact+R_regolith to t_surf."""
    import numpy as np
    from scipy.integrate import solve_bvp

    if n_nodes < 3 or length_m <= 0:
        return 0.0, t_surf_k, [t_root_k]
    r_foot = foot_thermal_resistance_k_per_w(footpad_area, h_contact, k_regolith)
    ka = k_leg * a_cross

    def fun(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        ql = np.array(
            [
                radiative_loss_per_length_w(
                    float(Ti), perimeter_m, leg_emissivity, t_sky_k, t_ground_k, f_sky, f_ground, sigma
                )
                for Ti in y[0]
            ],
            dtype=float,
        ) / ka
        return np.vstack((y[1], ql))

    def bc(ya: np.ndarray, yb: np.ndarray) -> np.ndarray:
        q_foot = (yb[0] - t_surf_k) / r_foot
        return np.array([ya[0] - t_root_k, -ka * yb[1] - q_foot])

    x = np.linspace(0.0, length_m, max(3, n_nodes))
    tg = np.linspace(t_root_k, max(t_surf_k, t_root_k * 0.5), n_nodes)
    y0 = np.vstack([tg, np.gradient(tg, x, edge_order=2)])
    node_cap = max_nodes if max_nodes is not None else max(8000, 4 * n_nodes)
    sol = solve_bvp(fun, bc, x, y0, tol=rtol, max_nodes=node_cap, verbose=0)
    if not sol.success:
        raise FinSolverError(f"Radiating leg BVP failed (n_mesh={n_nodes}): {sol.message}")
    max_res = float(np.max(np.abs(sol.rms_residuals))) if sol.rms_residuals is not None else 0.0
    if max_res > max(1e-3, rtol * 100):
        raise FinSolverError(f"Radiating leg BVP residual too large: {max_res}")

    x_f = sol.x
    T_f = sol.sol(x_f)[0]
    q_rad = _integrate_radiative_heat(x_f, T_f, perimeter_m, leg_emissivity, t_sky_k, t_ground_k, f_sky, f_ground, sigma)
    t_foot = float(T_f[-1])
    q_foot = (t_foot - t_surf_k) / r_foot if r_foot > 0 else 0.0
    q_total = max(0.0, q_rad + q_foot)
    profile = np.interp(np.linspace(0, length_m, n_nodes), x_f, T_f).tolist()
    return q_total, t_foot, profile


def legs_total_loss_w(
    n_legs: int,
    k_leg: float,
    a_cross: float,
    perimeter_m: float,
    length_m: float,
    leg_eps: float,
    t_box_k: float,
    t_sky_k: float,
    t_ground_k: float,
    t_surf_k: float,
    footpad_area: float,
    h_contact: float,
    k_regolith: float,
    f_sky: float,
    f_ground: float,
    n_segments: int,
    sigma: float,
) -> Tuple[float, float, float]:
    """Single fin model only (radiation + foot R to regolith). Returns Q_total, T_foot, Q at surface k."""
    if n_legs <= 0:
        raise ConfigError("lander_legs.n_legs must be positive.")
    q_one, t_foot, _ = solve_radiating_leg_fin(
        k_leg, a_cross, perimeter_m, length_m, leg_eps, t_box_k, t_sky_k, t_ground_k, t_surf_k,
        f_sky, f_ground, footpad_area, h_contact, k_regolith, n_segments, sigma,
    )
    return n_legs * q_one, t_foot, q_one


@dataclass
class ThermalLoss:
    q_box_rad_w: float
    q_leg_w: float
    q_leg_at_surface_k_w: float
    q_leg_at_depth_k_w: float
    t_leg_foot_k: float
    q_passthrough_w: float
    q_total_w: float
    q_total_at_depth_k_w: float
    area_radiating_m2: float


def leg_perimeter_m(cfg: Dict[str, Any]) -> float:
    p = param_value(cfg, "lander_legs", "leg_perimeter_m")
    if p is not None and p > 0:
        return float(p)
    raise ConfigError("lander_legs.leg_perimeter_m must be set (TODO-luke — tube/hollow strut wetted perimeter).")


def compute_thermal_loss(
    cfg: Dict[str, Any],
    emittance: Optional[float] = None,
    k_leg: Optional[float] = None,
    t_box_k: Optional[float] = None,
) -> ThermalLoss:
    t_box = t_box_k if t_box_k is not None else param_value(cfg, "battery", "box_target_temperature_k")
    t_sky = param_value(cfg, "thermal_environment", "deep_space_sink_k")
    t_ground = param_value(cfg, "thermal_environment", "night_surface_k")
    t_deck = param_value(cfg, "thermal_environment", "lander_deck_temperature_k")
    k_reg_surf = param_value(cfg, "thermal_environment", "regolith_k_surface_w_per_mk")
    k_reg_depth = param_value(cfg, "thermal_environment", "regolith_k_depth_w_per_mk")
    h_contact = param_value(cfg, "thermal_environment", "footpad_contact_conductance_w_per_m2k")

    e_box = emittance if emittance is not None else param_value(cfg, "radiation", "box_effective_emittance")
    e_mult = param_value(cfg, "radiation", "penetration_seam_emittance_multiplier") or 1.0
    sigma = param_value(cfg, "physics", "stefan_boltzmann_w_per_m2k4") or SIGMA_DEFAULT

    n_boxes = param_value(cfg, "geometry", "n_battery_boxes")
    box_l = param_value(cfg, "geometry", "box_length_m")
    box_w = param_value(cfg, "geometry", "box_width_m")
    box_h = param_value(cfg, "geometry", "box_height_m")
    ring_r = param_value(cfg, "geometry", "ring_radius_m")
    bottom_to = param_value(cfg, "geometry", "bottom_radiates_to") or "ground"
    f_sky = param_value(cfg, "geometry", "view_factor_sky_vertical")
    f_g = param_value(cfg, "geometry", "view_factor_ground_vertical")

    n_legs = param_value(cfg, "lander_legs", "n_legs")
    k_leg = k_leg if k_leg is not None else param_value(cfg, "lander_legs", "leg_thermal_conductivity_w_per_mk")
    a_cross = param_value(cfg, "lander_legs", "leg_cross_section_m2")
    leg_len = param_value(cfg, "lander_legs", "leg_length_m")
    leg_eps = param_value(cfg, "lander_legs", "leg_surface_emissivity")
    footpad_a = param_value(cfg, "lander_legs", "footpad_area_m2")
    n_seg = param_value(cfg, "lander_legs", "leg_fin_segments") or 12
    perim = leg_perimeter_m(cfg)

    passthrough = param_value(cfg, "losses", "passthrough_w") or 0.0

    if bottom_to == "lander_deck" and t_deck is None:
        raise ConfigError("bottom_radiates_to=lander_deck requires thermal_environment.lander_deck_temperature_k")
    t_bottom_sink = t_deck if bottom_to == "lander_deck" else t_ground

    q_rad, area, _ = box_radiation_loss_w(
        n_boxes, box_l, box_w, box_h, ring_r, e_box, t_box, t_sky, t_ground, t_bottom_sink,
        bottom_to, f_sky, f_g, e_mult, sigma,
    )
    q_leg_surf, t_foot, _ = legs_total_loss_w(
        n_legs, k_leg, a_cross, perim, leg_len, leg_eps, t_box, t_sky, t_ground, t_ground,
        footpad_a, h_contact, k_reg_surf, f_sky, f_g, n_seg, sigma,
    )
    q_leg_depth, _, _ = legs_total_loss_w(
        n_legs, k_leg, a_cross, perim, leg_len, leg_eps, t_box, t_sky, t_ground, t_ground,
        footpad_a, h_contact, k_reg_depth, f_sky, f_g, n_seg, sigma,
    )
    q_total_surf = q_rad + q_leg_surf + passthrough
    q_total_depth = q_rad + q_leg_depth + passthrough
    return ThermalLoss(
        q_box_rad_w=q_rad,
        q_leg_w=q_leg_surf,
        q_leg_at_surface_k_w=q_leg_surf,
        q_leg_at_depth_k_w=q_leg_depth,
        t_leg_foot_k=t_foot,
        q_passthrough_w=passthrough,
        q_total_w=q_total_surf,
        q_total_at_depth_k_w=q_total_depth,
        area_radiating_m2=area,
    )


def net_rtg_need_w(q_loss_w: float, q_internal_w: float, coupling: Optional[float]) -> Tuple[Optional[float], float]:
    """Q_RTG = max(0, Q_loss - Q_internal) / coupling; excess if internal > loss."""
    excess = max(0.0, q_internal_w - q_loss_w)
    net = max(0.0, q_loss_w - q_internal_w)
    if coupling is None:
        return None, excess
    if coupling <= 0:
        raise ConfigError("rtg.coupling_fraction must be positive")
    return net / coupling, excess


def heater_shortfall_w(q_loss_w: float, q_internal_w: float, coupling: float, q_rtg_given_w: float) -> float:
    delivered = coupling * q_rtg_given_w + q_internal_w
    return max(0.0, q_loss_w - delivered)


def informational_radiative_coupling(
    n_boxes: int,
    length_m: float,
    height_m: float,
    ring_radius_m: float,
    absorptance: Optional[float],
) -> Optional[float]:
    """
    Fraction of isotropic point-source thermal emission intercepted by inward faces
    (geometric estimate only — NOT a design value).
    """
    if absorptance is None or n_boxes <= 0 or ring_radius_m <= 0:
        return None
    a_in = length_m * height_m
    # Geometric: flux at distance r from isotropic source P: P/(4*pi*r^2); face at angle ~normal to radius
    flux_frac = 0.0
    for _ in range(n_boxes):
        solid = a_in / (4.0 * math.pi * ring_radius_m**2)
        flux_frac += solid
    return min(1.0, flux_frac * absorptance)


def lumped_transient_delta_t_k(
    q_net_w: float,
    mass_kg: float,
    cp_j_kgk: float,
    t_dark_h: float,
) -> Optional[float]:
    """Delta T over night with no RTG if net heat out is q_net_w (positive = cooling)."""
    if cp_j_kgk is None or cp_j_kgk <= 0 or mass_kg <= 0:
        return None
    e_out_j = q_net_w * t_dark_h * 3600.0
    return -e_out_j / (mass_kg * cp_j_kgk)


def thermal_q_loss_at_box_t(cfg: Dict[str, Any], t_box_k: float) -> float:
    return compute_thermal_loss(cfg, t_box_k=t_box_k).q_total_w


def build_q_loss_temperature_lut(
    cfg: Dict[str, Any], t_min_k: float = 40.0, t_max_k: float = 280.0, n_points: int = 50
) -> Tuple[List[float], List[float]]:
    """Precompute Q_loss(T) for fast lumped transient integration."""
    import numpy as np

    temps = [float(x) for x in np.linspace(t_min_k, t_max_k, max(5, n_points))]
    q_vals = [thermal_q_loss_at_box_t(cfg, t) for t in temps]
    return temps, q_vals


def q_loss_from_lut(t_k: float, temps: List[float], q_vals: List[float]) -> float:
    import numpy as np

    return float(np.interp(t_k, temps, q_vals, left=q_vals[0], right=q_vals[-1]))


def integrate_lumped_thermal_coast(
    cfg: Dict[str, Any],
    mass_kg: float,
    cp_j_kgk: float,
    t_start_k: float,
    duration_h: float,
    *,
    p_load_w: float = 0.0,
    p_heater_w: float = 0.0,
    eta: float = 0.9,
    eta_definition: str = "discharge",
    dt_s: float = 120.0,
    lipo_limit_k: Optional[float] = None,
    q_loss_lut: Optional[Tuple[List[float], List[float]]] = None,
) -> Dict[str, Any]:
    """Lumped capacitance with Q_loss(T) from thermal model; optional electrical loads."""
    if mass_kg <= 0 or cp_j_kgk <= 0 or duration_h <= 0:
        raise ValueError("mass, cp, and duration must be positive")
    mc = mass_kg * cp_j_kgk
    q_int_load, _ = pick_internal_heat(internal_waste_heat_w(p_load_w, eta), eta_definition)
    q_int_heat, _ = pick_internal_heat(internal_waste_heat_w(p_heater_w, eta), eta_definition)
    t = 0.0
    t_end_s = duration_h * 3600.0
    temp = t_start_k
    energy_out_j = 0.0
    time_to_lipo_h: Optional[float] = None
    while t < t_end_s - 1e-9:
        step = min(dt_s, t_end_s - t)
        if q_loss_lut is not None:
            q_loss = q_loss_from_lut(temp, q_loss_lut[0], q_loss_lut[1])
        else:
            q_loss = thermal_q_loss_at_box_t(cfg, temp)
        q_in = q_int_load + q_int_heat + p_heater_w
        q_net_out = q_loss - q_in
        energy_out_j += q_net_out * step
        temp -= q_net_out * step / mc
        t += step
        if lipo_limit_k is not None and time_to_lipo_h is None and temp <= lipo_limit_k:
            time_to_lipo_h = t / 3600.0
    return {
        "t_final_k": temp,
        "time_to_lipo_h": time_to_lipo_h,
        "margin_lipo_k": (temp - lipo_limit_k) if lipo_limit_k is not None else None,
        "energy_net_out_kwh": max(0.0, energy_out_j / 3.6e6),
    }


def solve_dawn_warmup_heater_w(
    cfg: Dict[str, Any],
    mass_kg: float,
    cp_j_kgk: float,
    t_start_k: float,
    t_target_k: float,
    warm_up_h: float,
    eta: float,
    eta_definition: str,
    dt_s: float = 120.0,
    q_loss_lut: Optional[Tuple[List[float], List[float]]] = None,
) -> Dict[str, float]:
    """Bisection on resistive heater power to reach t_target within warm_up_h."""
    if warm_up_h <= 0 or t_target_k <= t_start_k:
        return {"p_heater_w": 0.0, "energy_wh": 0.0}

    def temp_at_end(p_h: float) -> float:
        coast = integrate_lumped_thermal_coast(
            cfg,
            mass_kg,
            cp_j_kgk,
            t_start_k,
            warm_up_h,
            p_heater_w=p_h,
            eta=eta,
            eta_definition=eta_definition,
            dt_s=dt_s,
            q_loss_lut=q_loss_lut,
        )
        return coast["t_final_k"]

    lo, hi = 0.0, max(500.0, thermal_q_loss_at_box_t(cfg, t_start_k) * 3.0)
    for _ in range(8):
        if temp_at_end(hi) >= t_target_k:
            break
        hi *= 2.0
    else:
        raise ConfigError("dawn warm-up: could not bracket heater power — extend warm_up_h or check inputs")
    p_solve = hi
    for _ in range(32):
        mid = 0.5 * (lo + hi)
        if temp_at_end(mid) >= t_target_k:
            hi = mid
            p_solve = mid
        else:
            lo = mid
    coast = integrate_lumped_thermal_coast(
        cfg,
        mass_kg,
        cp_j_kgk,
        t_start_k,
        warm_up_h,
        p_heater_w=p_solve,
        eta=eta,
        eta_definition=eta_definition,
        dt_s=dt_s,
        q_loss_lut=q_loss_lut,
    )
    e_heater_wh = p_solve * warm_up_h
    return {"p_heater_w": p_solve, "energy_wh": e_heater_wh, "t_final_k": coast["t_final_k"]}


@dataclass
class CaseResult:
    load_name: str
    load_w: float
    specific_energy_wh_kg: float
    fallback_branch: str
    battery: BatterySizing
    thermal: ThermalLoss
    q_internal_w: float
    q_internal_note: str
    q_internal_both: Dict[str, float]
    q_excess_w: float
    q_rtg_total_w: Optional[float]
    q_rtg_message: str
    q_rtg_per_unit_w: Dict[int, float]
    mode: str
    iterations: int
    transient_delta_t_k: Optional[float]
    transient_below_lipo: Optional[bool]
    transient_warning: Optional[str]
    radiative_coupling_info: Optional[float]
    coast_t_final_k: Optional[float] = None
    coast_time_to_lipo_h: Optional[float] = None
    coast_margin_lipo_k: Optional[float] = None
    coast_energy_out_kwh: Optional[float] = None
    dawn_warmup_target_k: Optional[float] = None
    dawn_warmup_p_heater_w: Optional[float] = None
    dawn_warmup_energy_wh: Optional[float] = None
    dawn_warmup_note: Optional[str] = None


def scaled_geometry_for_separate_pack(
    cfg: Dict[str, Any], pack_mass_kg: float, specific_energy_wh_kg: float
) -> Optional[Dict[str, float]]:
    rho = param_value(cfg, "fallback", "pack_volumetric_energy_density_wh_per_m3")
    if rho is None or rho <= 0:
        return None
    capacity_wh = pack_mass_kg * specific_energy_wh_kg
    volume_m3 = capacity_wh / rho
    n = param_value(cfg, "geometry", "n_battery_boxes")
    if not n:
        return None
    h = param_value(cfg, "geometry", "box_height_m")
    l = param_value(cfg, "geometry", "box_length_m")
    w = param_value(cfg, "geometry", "box_width_m")
    if not all([h, l, w]):
        return None
    vol_per_box = volume_m3 / n
    scale = (vol_per_box / (l * w * h)) ** (1.0 / 3.0)
    return {"scale": scale, "volume_m3": volume_m3}


def solve_case(
    load_name: str,
    load_w: float,
    specific_energy: float,
    cfg: Dict[str, Any],
    fallback_branch: str = "primary",
    emittance: Optional[float] = None,
    k_leg: Optional[float] = None,
    primary_pack: Optional[BatterySizing] = None,
    transient_mass_kg: Optional[float] = None,
    max_iter: int = 40,
    tol_w: float = 1e-2,
) -> CaseResult:
    validate_for_run(cfg)
    mode = param_value(cfg, "meta", "mode") or "solve_rtg"
    t_dark = param_value(cfg, "night", "t_dark_h")
    dod = param_value(cfg, "battery", "depth_of_discharge")
    eta = battery_efficiency_value(cfg)
    eta_def = param_value(cfg, "battery", "eta_definition")
    if not eta_def:
        raise ConfigError("battery.eta_definition must be round_trip or discharge")
    packaging = param_value(cfg, "battery", "packaging_insulation_mass_factor")
    bus_v = param_value(cfg, "battery", "bus_voltage_v")
    cell_v = param_value(cfg, "battery", "cell_nominal_voltage_v")
    cell_ah = param_value(cfg, "battery", "cell_capacity_ah")
    cp = param_value(cfg, "battery", "pack_specific_heat_j_per_kgk")
    lipo_lim = param_value(cfg, "battery", "lipo_cold_limit_k")
    t_box = param_value(cfg, "battery", "box_target_temperature_k")

    eta_dis = discharge_efficiency_for_sizing(eta, eta_def)
    coupling = param_value(cfg, "rtg", "coupling_fraction")
    rtg_counts: List[int] = param_value(cfg, "rtg", "count_list") or []
    q_rtg_fixed = param_value(cfg, "rtg", "thermal_output_w")

    q_int_map = internal_waste_heat_w(load_w, eta)
    q_internal, q_note = pick_internal_heat(q_int_map, eta_def)

    p_heater = 0.0
    iterations = 0
    thermal_cfg = cfg
    geometry_scales = fallback_branch == "separate_pack"
    iterate = geometry_scales or mode == "fixed_rtg"

    for loop_i in range(max_iter if iterate else 1):
        iterations = loop_i + 1
        battery = size_battery_pack(
            load_w, p_heater, t_dark, dod, eta_dis, specific_energy, packaging, bus_v, cell_v, cell_ah
        )
        if fallback_branch == "same_pack_survival":
            if primary_pack is None:
                raise ConfigError("same_pack_survival requires primary_pack (reuse primary mass/geometry)")
            battery.mass_kg = primary_pack.mass_kg
            battery.capacity_wh = primary_pack.capacity_wh
        if geometry_scales:
            scale_info = scaled_geometry_for_separate_pack(cfg, battery.mass_kg, specific_energy)
            if scale_info:
                import copy

                thermal_cfg = copy.deepcopy(cfg)
                s = scale_info["scale"]
                for key in ("box_length_m", "box_width_m", "box_height_m"):
                    thermal_cfg["geometry"][key]["value"] = param_value(cfg, "geometry", key) * s

        thermal = compute_thermal_loss(thermal_cfg, emittance=emittance, k_leg=k_leg)
        if mode == "fixed_rtg":
            if q_rtg_fixed is None:
                raise ConfigError("mode=fixed_rtg requires rtg.thermal_output_w")
            if coupling is None:
                raise ConfigError("fixed_rtg requires rtg.coupling_fraction")
            new_heater = heater_shortfall_w(thermal.q_total_w, q_internal, coupling, float(q_rtg_fixed))
            if abs(new_heater - p_heater) < tol_w:
                p_heater = new_heater
                break
            p_heater = new_heater
        else:
            p_heater = 0.0
            break
    else:
        if iterate:
            sys.stderr.write(f"Warning: heater/geometry loop hit max_iter={max_iter} ({load_name})\n")

    if mode == "fixed_rtg" and q_rtg_fixed is not None:
        q_rtg_total = float(q_rtg_fixed)
        q_msg = "fixed_rtg mode — using rtg.thermal_output_w"
        excess = max(0.0, q_internal - thermal.q_total_w)
    elif coupling is None:
        q_rtg_total = None
        q_msg = "RTG need cannot be computed until rtg.coupling_fraction is chosen (Q_loss reported)."
        excess = max(0.0, q_internal - thermal.q_total_w)
    else:
        q_rtg_total, excess = net_rtg_need_w(thermal.q_total_w, q_internal, coupling)
        q_msg = "solve_rtg: Q_RTG = max(0,Q_loss-Q_internal)/coupling"

    per_unit = {n: q_rtg_total / n for n in rtg_counts if n > 0 and q_rtg_total is not None}

    mass_for_transient = transient_mass_kg or (primary_pack.mass_kg if primary_pack else battery.mass_kg)
    q_net_no_rtg = thermal.q_total_w - q_internal
    dT = lumped_transient_delta_t_k(q_net_no_rtg, mass_for_transient, cp, t_dark)
    below_lipo = (t_box + dT < lipo_lim) if dT is not None else None
    twarn = None
    if dT is not None:
        if t_box + dT < 0:
            twarn = f"nonphysical transient: T_final={t_box + dT:.1f} K (< 0)"
        elif below_lipo:
            twarn = f"transient below LiPo limit ({lipo_lim} K)"

    rad_couple = informational_radiative_coupling(
        param_value(cfg, "geometry", "n_battery_boxes"),
        param_value(cfg, "geometry", "box_length_m"),
        param_value(cfg, "geometry", "box_height_m"),
        param_value(cfg, "geometry", "ring_radius_m"),
        param_value(cfg, "rtg", "inward_face_absorptance"),
    )

    return CaseResult(
        load_name=load_name,
        load_w=load_w,
        specific_energy_wh_kg=specific_energy,
        fallback_branch=fallback_branch,
        battery=battery,
        thermal=thermal,
        q_internal_w=q_internal,
        q_internal_note=q_note,
        q_internal_both=q_int_map,
        q_excess_w=excess,
        q_rtg_total_w=q_rtg_total,
        q_rtg_message=q_msg,
        q_rtg_per_unit_w=per_unit,
        mode=mode,
        iterations=iterations,
        transient_delta_t_k=dT,
        transient_below_lipo=below_lipo,
        transient_warning=twarn,
        radiative_coupling_info=rad_couple,
    )


def solve_cold_shutdown_case(
    cfg: Dict[str, Any],
    primary: CaseResult,
    *,
    dt_s: float = 120.0,
) -> CaseResult:
    """Zero load backup: coast through night with Q_loss(T), then dawn warm-up heater estimate."""
    validate_for_run(cfg)
    t_dark = param_value(cfg, "night", "t_dark_h")
    eta = battery_efficiency_value(cfg)
    eta_def = param_value(cfg, "battery", "eta_definition")
    cp = param_value(cfg, "battery", "pack_specific_heat_j_per_kgk")
    lipo_lim = param_value(cfg, "battery", "lipo_cold_limit_k")
    t_box = param_value(cfg, "battery", "box_target_temperature_k")
    t_min_charge = param_value(cfg, "battery", "minimum_charge_temperature_k")
    warm_h = param_value(cfg, "battery", "dawn_warm_up_h")
    if cp is None or cp <= 0:
        raise ConfigError("cold_shutdown transient requires battery.pack_specific_heat_j_per_kgk")
    if warm_h is None or warm_h <= 0:
        raise ConfigError("dawn warm-up requires battery.dawn_warm_up_h")

    mass = primary.battery.mass_kg
    lut = build_q_loss_temperature_lut(cfg, t_min_k=min(lipo_lim or 40, t_box) - 10, t_max_k=t_box + 5)
    coast = integrate_lumped_thermal_coast(
        cfg,
        mass,
        cp,
        t_box,
        t_dark,
        p_load_w=0.0,
        eta=eta,
        eta_definition=eta_def,
        dt_s=dt_s,
        lipo_limit_k=lipo_lim,
        q_loss_lut=lut,
    )
    t_final = coast["t_final_k"]
    warmup_target = max(t_box, t_min_charge) if t_min_charge is not None else t_box
    warmup = solve_dawn_warmup_heater_w(
        cfg, mass, cp, t_final, warmup_target, warm_h, eta, eta_def, dt_s=dt_s, q_loss_lut=lut
    )

    thermal_hold = compute_thermal_loss(cfg)
    q_int_map = internal_waste_heat_w(0.0, eta)
    q_internal, q_note = pick_internal_heat(q_int_map, eta_def)
    battery = primary.battery
    battery = BatterySizing(
        p_load_w=0.0,
        p_heater_w=0.0,
        t_dark_h=t_dark,
        dod=battery.dod,
        eta_discharge=battery.eta_discharge,
        specific_energy_wh_kg=battery.specific_energy_wh_kg,
        packaging_factor=battery.packaging_factor,
        e_night_wh=0.0,
        capacity_wh=battery.capacity_wh,
        mass_kg=mass,
        n_series=battery.n_series,
        n_parallel=battery.n_parallel,
        energy_per_string_wh=battery.energy_per_string_wh,
        bus_v=battery.bus_v,
        cell_v=battery.cell_v,
        cell_ah=battery.cell_ah,
    )
    dT = coast["t_final_k"] - t_box
    note = (
        "Energy from solar wake-up circuit before charge is allowed "
        "(charging blocked below minimum_charge_temperature_k)."
    )
    return CaseResult(
        load_name="cold_shutdown_0W",
        load_w=0.0,
        specific_energy_wh_kg=primary.specific_energy_wh_kg,
        fallback_branch="cold_shutdown",
        battery=battery,
        thermal=thermal_hold,
        q_internal_w=q_internal,
        q_internal_note=q_note,
        q_internal_both=q_int_map,
        q_excess_w=0.0,
        q_rtg_total_w=0.0,
        q_rtg_message="design uses 5 kW primary — RTG thermal not required (backup case only)",
        q_rtg_per_unit_w={},
        mode=param_value(cfg, "meta", "mode") or "solve_rtg",
        iterations=1,
        transient_delta_t_k=dT,
        transient_below_lipo=coast["margin_lipo_k"] is not None and coast["margin_lipo_k"] < 0,
        transient_warning=None,
        radiative_coupling_info=primary.radiative_coupling_info,
        coast_t_final_k=coast["t_final_k"],
        coast_time_to_lipo_h=coast["time_to_lipo_h"],
        coast_margin_lipo_k=coast["margin_lipo_k"],
        coast_energy_out_kwh=coast["energy_net_out_kwh"],
        dawn_warmup_target_k=warmup_target,
        dawn_warmup_p_heater_w=warmup["p_heater_w"],
        dawn_warmup_energy_wh=warmup["energy_wh"],
        dawn_warmup_note=note,
    )


def todo_luke_list(cfg: Dict[str, Any]) -> List[str]:
    rows = []
    for row in flatten_inputs(cfg):
        if row["owner"] == "TODO-luke":
            suffix = " (unset)" if row["value"] == "(unset)" else ""
            rows.append(f"{row['path']}: {row['value']} {row['units']} — {row['source']}{suffix}")
    return rows


def pack_efficiency_from_case(r: CaseResult) -> float:
    b = r.battery
    if b.p_load_w > 0 and r.q_internal_w >= 0:
        return b.p_load_w / (b.p_load_w + r.q_internal_w)
    return b.eta_discharge


def _internal_waste_key(eta_definition: str) -> str:
    return "discharge_definition" if eta_definition == "discharge" else "round_trip_definition"


def electric_heater_alternative(r: CaseResult) -> Optional[Dict[str, float]]:
    """Steady resistive heat (includes battery discharge loss on heater current)."""
    gap = r.thermal.q_total_w - r.q_internal_w
    if gap <= 0:
        return None
    eta = pack_efficiency_from_case(r)
    wkey = _internal_waste_key(r.q_internal_note)
    p_heater = gap * eta
    q_int_h = internal_waste_heat_w(p_heater, eta)[wkey]
    for _ in range(8):
        p_new = max(0.0, (r.thermal.q_total_w - r.q_internal_w - q_int_h) * eta)
        q_int_h = internal_waste_heat_w(p_new, eta)[wkey]
        if abs(p_new - p_heater) < 1e-2:
            p_heater = p_new
            break
        p_heater = p_new
    e_heater_wh = p_heater * r.battery.t_dark_h
    capacity_extra_wh = e_heater_wh / (r.battery.dod * r.battery.eta_discharge)
    return {
        "p_shortfall_w": p_heater,
        "q_internal_from_heater_w": q_int_h,
        "e_heater_wh": e_heater_wh,
        "capacity_extra_wh": capacity_extra_wh,
    }


def format_electric_heater_alt_line(r: CaseResult) -> Optional[str]:
    if r.fallback_branch != "same_pack_survival":
        return None
    alt = electric_heater_alternative(r)
    if alt is None:
        return None
    b = r.battery
    return (
        f"  Electric-heater alt (vs RTG thermal): P_heat={alt['p_shortfall_w']:.1f} W steady → "
        f"{alt['e_heater_wh']/1000:.3f} kWh over {b.t_dark_h:.0f} h; "
        f"+{alt['capacity_extra_wh']/1000:.3f} kWh capacity increment "
        f"(DoD={b.dod}, η_dis={b.eta_discharge:.3f}; includes heater discharge loss)"
    )


def placeholder_list(cfg: Dict[str, Any]) -> List[str]:
    rows = []
    for row in flatten_inputs(cfg):
        if row["owner"] == "placeholder":
            rows.append(f"{row['path']}: {row['value']} {row['units']} — {row['source']}")
    return rows


def format_results_table(results: List[CaseResult], coupling_set: bool, cfg: Optional[Dict[str, Any]] = None) -> str:
    lines = ["", "=" * 100, "LUNAR BASE BATTERY + RTG THERMAL SIZER", "=" * 100]
    if not coupling_set:
        lines.append("NOTE: rtg.coupling_fraction unset — RTG totals omitted; Q_loss only.")
    for r in results:
        lines.append(
            f"\n--- {r.load_name} [{r.fallback_branch}] @ {r.specific_energy_wh_kg} Wh/kg "
            f"(mode={r.mode}, iter={r.iterations}) ---"
        )
        b = r.battery
        lines.append(f"  P_load        = {b.p_load_w:.1f} W")
        lines.append(f"  P_heater      = {b.p_heater_w:.1f} W")
        lines.append(f"  Q_internal    = {r.q_internal_w:.1f} W ({r.q_internal_note})")
        lines.append(
            f"    (also round_trip={r.q_internal_both['round_trip_definition']:.1f} W, "
            f"discharge={r.q_internal_both['discharge_definition']:.1f} W)"
        )
        lines.append(f"  E_night       = {b.e_night_wh/1000:.3f} kWh")
        lines.append(f"  Capacity C    = {b.capacity_wh/1000:.3f} kWh (discharge eta={b.eta_discharge:.4f})")
        lines.append(f"  Pack mass     = {b.mass_kg:.1f} kg")
        lines.append(f"  N_series      = {b.n_series}")
        lines.append(
            f"  Q_loss total  = {r.thermal.q_total_w:.1f} W "
            f"(box rad {r.thermal.q_box_rad_w:.1f}, legs {r.thermal.q_leg_w:.1f}, foot≈{r.thermal.t_leg_foot_k:.0f} K)"
        )
        lines.append(
            f"  Q_loss @ Hayne depth k = {r.thermal.q_total_at_depth_k_w:.1f} W "
            f"(legs {r.thermal.q_leg_at_depth_k_w:.1f} W)"
        )
        if r.load_name == "primary_5000W" and r.q_excess_w > 0:
            e_reject_kwh = r.q_excess_w * r.battery.t_dark_h / 1000.0
            d_t = r.transient_delta_t_k if r.transient_delta_t_k is not None else 0.0
            lines.append(
                f"  Excess heat to reject (cooling): {r.q_excess_w:.1f} W; {e_reject_kwh:.2f} kWh over "
                f"{r.battery.t_dark_h:.0f} h night; lumped ΔT at hold ≈ {d_t:.1f} K (RTG thermal not in 5 kW design)"
            )
        elif r.q_excess_w > 0:
            lines.append(f"  Q_excess      = {r.q_excess_w:.1f} W (overheat risk — internal > loss)")
        if r.q_rtg_total_w is not None:
            lines.append(f"  Q_RTG total   = {r.q_rtg_total_w:.1f} W — {r.q_rtg_message}")
            for n, q in sorted(r.q_rtg_per_unit_w.items()):
                lines.append(f"    per RTG n={n}: {q:.1f} W")
        else:
            lines.append(f"  Q_RTG         — {r.q_rtg_message}")
        if r.radiative_coupling_info is not None:
            lines.append(f"  Info only: radiative coupling estimate ≈ {r.radiative_coupling_info:.4f}")
        if r.transient_delta_t_k is not None:
            lines.append(f"  Transient ΔT (passive coast, no RTG) ≈ {r.transient_delta_t_k:.2f} K")
        alt_line = format_electric_heater_alt_line(r)
        if alt_line:
            lines.append(alt_line)
        if r.fallback_branch == "cold_shutdown" and r.coast_t_final_k is not None:
            t0 = r.coast_t_final_k - (r.transient_delta_t_k or 0.0)
            lines.append(
                f"  Cold shutdown coast: {t0:.2f} K → {r.coast_t_final_k:.2f} K over {r.battery.t_dark_h:.0f} h; "
                f"energy out ≈ {r.coast_energy_out_kwh:.2f} kWh"
            )
            if r.coast_time_to_lipo_h is not None:
                lines.append(f"  Time to LiPo limit: {r.coast_time_to_lipo_h:.2f} h")
            elif r.coast_margin_lipo_k is not None:
                lines.append(f"  LiPo margin at dawn: {r.coast_margin_lipo_k:.2f} K")
            if r.dawn_warmup_p_heater_w is not None and r.dawn_warmup_target_k is not None:
                lines.append(
                    f"  Dawn warm-up → {r.dawn_warmup_target_k:.1f} K: "
                    f"P_heater≈{r.dawn_warmup_p_heater_w:.1f} W, E≈{r.dawn_warmup_energy_wh/1000:.2f} kWh"
                )
                if r.dawn_warmup_note:
                    lines.append(f"  {r.dawn_warmup_note}")
        if r.transient_warning:
            lines.append(f"  WARNING: {r.transient_warning}")
    lines.append(
        "\nThermal driver note: effective emittance × radiating area dominates Q_loss; "
        "T_sky/T_ground shifts are small compared to T_box."
    )
    lines.append(
        "Regolith spreading: R=1/(4ka) — Hayne et al. 2017 k≈7.4e-4 W/m·K (surface) "
        "and 3.4e-3 W/m·K (~6–7 cm depth); legs use surface k unless Luke revises."
    )
    return "\n".join(lines)


def run_all_cases(cfg: Dict[str, Any]) -> List[CaseResult]:
    se_low = param_value(cfg, "battery", "specific_energy_wh_per_kg_low")
    se_high = param_value(cfg, "battery", "specific_energy_wh_per_kg_high")
    primary_w = param_value(cfg, "loads", "primary_w")
    loads = [
        ("primary_5000W", primary_w),
        ("survival_100W", param_value(cfg, "loads", "survival_high_w")),
        ("survival_50W", param_value(cfg, "loads", "survival_low_w")),
    ]
    fb = param_value(cfg, "fallback", "mode")
    survival_branches = ["same_pack_survival", "separate_pack"] if fb is None else [fb]

    primary_by_se: Dict[float, CaseResult] = {}
    for se in (se_low, se_high):
        primary_by_se[se] = solve_case("primary_5000W", primary_w, se, cfg, fallback_branch="primary")

    results: List[CaseResult] = []
    for name, pw in loads:
        is_primary = "primary" in name
        branch_list = ["primary"] if is_primary else survival_branches
        for se in (se_low, se_high):
            for br in branch_list:
                if is_primary:
                    results.append(primary_by_se[se])
                    continue
                prim = primary_by_se[se].battery
                results.append(
                    solve_case(
                        name,
                        pw,
                        se,
                        cfg,
                        fallback_branch=br,
                        primary_pack=prim if br == "same_pack_survival" else None,
                        transient_mass_kg=prim.mass_kg if br == "same_pack_survival" else None,
                    )
                )

    for se in (se_low, se_high):
        if se in primary_by_se:
            try:
                results.append(solve_cold_shutdown_case(cfg, primary_by_se[se]))
            except (ConfigError, ValueError):
                pass
    return results


def run_sensitivity(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    loads = [
        ("primary", param_value(cfg, "loads", "primary_w")),
        ("survival_high", param_value(cfg, "loads", "survival_high_w")),
    ]
    se_low = param_value(cfg, "battery", "specific_energy_wh_per_kg_low")
    em_list = cfg.get("radiation", {}).get("emittance_sensitivity", [])
    rows: List[Dict[str, Any]] = []
    for load_name, load_w in loads:
        for em_entry in em_list:
            r = solve_case(load_name, load_w, se_low, cfg, emittance=em_entry["value"])
            rows.append(
                {
                    "load": load_name,
                    "emittance_label": em_entry.get("label", ""),
                    "mass_kg": r.battery.mass_kg,
                    "q_rtg_w": r.q_rtg_total_w,
                    "q_loss_w": r.thermal.q_total_w,
                }
            )
    return rows


def write_report_pdf(
    path: Path,
    cfg: Dict[str, Any],
    results: List[CaseResult],
    sensitivity: List[Dict[str, Any]],
    todos: List[str],
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    coupling_set = param_value(cfg, "rtg", "coupling_fraction") is not None

    with PdfPages(path) as pdf:
        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.axis("off")
        title = param_value(cfg, "meta", "title")
        ax.text(0.05, 0.98, str(title), fontsize=12, fontweight="bold", va="top")
        ax.text(
            0.05,
            0.93,
            "AI-assisted implementation (Cursor cloud agent, directed by Luke via Grok Bot).\n"
            "Cited parameters researched with AI assistance and labeled in config.\n"
            "e* × area drives thermal loss; T_sky/T_ground are secondary.",
            fontsize=7,
            va="top",
        )
        y = 0.86
        for row in flatten_inputs(cfg)[:50]:
            ax.text(0.05, y, f"{row['path']}: {row['value']} [{row['owner']}]", fontsize=5, family="monospace")
            y -= 0.016
            if y < 0.05:
                break
        pdf.savefig(fig)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.axis("off")
        y = 0.98
        for r in results[:18]:
            block = (
                f"{r.load_name}/{r.fallback_branch} @ {r.specific_energy_wh_kg} Wh/kg\n"
                f" mass={r.battery.mass_kg:.0f}kg Q_int={r.q_internal_w:.0f}W Q_loss={r.thermal.q_total_w:.0f}W"
            )
            if r.q_rtg_total_w is not None:
                block += f" Q_RTG={r.q_rtg_total_w:.0f}W"
            if r.q_excess_w > 0:
                block += f" EXCESS={r.q_excess_w:.0f}W"
            if r.transient_delta_t_k is not None:
                block += f" dT={r.transient_delta_t_k:.1f}K"
            if r.fallback_branch == "cold_shutdown" and r.coast_t_final_k is not None:
                block += f" Tf={r.coast_t_final_k:.1f}K"
            if r.dawn_warmup_energy_wh:
                block += f" warm={r.dawn_warmup_energy_wh/1000:.1f}kWh"
            ax.text(0.05, y, block, fontsize=7, family="monospace", va="top")
            y -= 0.055
            alt_line = format_electric_heater_alt_line(r)
            if alt_line:
                ax.text(0.05, y, alt_line.strip()[:120], fontsize=6, family="monospace", va="top")
                y -= 0.045
            y -= 0.02
        pdf.savefig(fig)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.axis("off")
        y = 0.95
        ph = placeholder_list(cfg)
        if ph:
            ax.text(0.05, y, "placeholder values (not Luke design):", fontweight="bold")
            y -= 0.025
            for t in ph[:20]:
                ax.text(0.05, y, f"• {t[:92]}", fontsize=5)
                y -= 0.018
        ax.text(0.05, max(0.35, y), "Values Luke still needs to choose:", fontweight="bold")
        y2 = max(0.32, y - 0.025)
        for t in todos:
            ax.text(0.05, y2, f"• {t[:92]}", fontsize=6)
            y2 -= 0.02
        if not coupling_set:
            ax.text(0.05, 0.15, "RTG need not computed — coupling_fraction unset.", fontsize=8)
        pdf.savefig(fig)
        plt.close(fig)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Lunar base battery + RTG thermal sizer")
    parser.add_argument("config", type=Path, help="Path to config YAML")
    parser.add_argument("--pdf", type=Path, default=None)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    try:
        validate_for_run(cfg)
    except DesignInputError as e:
        print("Luke needs to choose (required before run):")
        for m in e.missing:
            print(f"  • {m}")
        print("\nOptional TODO-luke (see config) may remain unset for partial reports.")
        return 2
    except ConfigError as e:
        print(f"Config error: {e}")
        return 2

    results = run_all_cases(cfg)
    sensitivity = run_sensitivity(cfg)
    todos = todo_luke_list(cfg)
    coupling_set = param_value(cfg, "rtg", "coupling_fraction") is not None

    placeholders = placeholder_list(cfg)
    print(format_results_table(results, coupling_set, cfg))
    if placeholders:
        print("\n--- placeholder (example values, not Luke's design) ---")
        for t in placeholders:
            print(f"  • {t}")
    print("\n--- TODO-luke (complete list) ---")
    for t in todos:
        print(f"  • {t}")

    pdf_path = args.pdf or Path(param_value(cfg, "output", "report_pdf") or "report.pdf")
    write_report_pdf(pdf_path, cfg, results, sensitivity, todos)
    print(f"\nWrote {pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())