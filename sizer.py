#!/usr/bin/env python3
"""
Lunar base battery pack thermal sizing — distributed packs with radiators (optional RTG module).
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
    ("layout", "model"),
    ("geometry", "n_packs"),
    ("geometry", "box_length_m"),
    ("geometry", "box_width_m"),
    ("geometry", "box_height_m"),
    ("lander_legs", "leg_cross_section_m2"),
    ("lander_legs", "leg_length_m"),
    ("lander_legs", "leg_surface_emissivity"),
    ("lander_legs", "footpad_area_m2"),
    ("battery", "packaging_insulation_mass_factor"),
    ("battery", "cell_nominal_voltage_v"),
    ("losses", "passthrough_w"),
    ("battery", "eta_definition"),
    ("lander_legs", "leg_perimeter_m"),
    ("battery", "pack_volumetric_energy_density_wh_per_m3"),
    ("radiator", "radiator_emissivity"),
    ("radiator", "radiator_temperature_k"),
    ("radiator", "radiator_areal_mass_kg_per_m2"),
    ("radiator", "louver_area_multiplier"),
    ("radiator", "radiator_closed_emissivity"),
    ("wake_up", "warm_up_h"),
    ("wake_up", "solar_constant_w_per_m2"),
    ("wake_up", "panel_efficiency"),
    ("wake_up", "sun_incidence_cosine"),
    ("wake_up", "panel_areal_mass_kg_per_m2"),
]

# TODO-luke fields that may stay null (still listed in report for Luke).
NON_BLOCKING_TODO_PATHS = {
    "battery.cell_capacity_ah",
    "battery.capacity_derating_factor_at_0c",
    "battery.minimum_charge_temperature_k",
    "battery.pack_specific_heat_j_per_kgk",
    "battery.lipo_margin_threshold_k",
    "thermal_environment.lander_deck_temperature_k",
    "rtg.thermal_output_w",
    "radiation.penetration_seam_emittance_multiplier",
    "rtg.inward_face_absorptance",
    "geometry.n_battery_boxes",
    "geometry.ring_radius_m",
    "rtg.coupling_fraction",
    "rtg.heat_path",
    "rtg.count_list",
    "rtg.inward_face_absorptance",
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
        if not isinstance(node, dict) or k not in node:
            return None
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
    n_boxes = param_value(cfg, "geometry", "n_packs")
    if n_boxes is None:
        n_boxes = param_value(cfg, "geometry", "n_battery_boxes")
    if n_boxes is not None and n_boxes <= 0:
        raise ConfigError("geometry.n_packs must be positive.")
    n_legs = param_value(cfg, "lander_legs", "n_legs")
    if n_legs is not None and n_legs <= 0:
        raise ConfigError("lander_legs.n_legs must be positive.")
    if rtg_module_enabled(cfg):
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


def per_pack_face_areas_m2(length_m: float, width_m: float, height_m: float) -> Dict[str, float]:
    """Isolated pack box: top sky, bottom ground, vertical sides 0.5 sky / 0.5 ground (no mutual view)."""
    vert = 2.0 * (length_m * height_m + width_m * height_m)
    return {
        "vertical_sides": vert,
        "top": length_m * width_m,
        "bottom": length_m * width_m,
    }


def total_pack_box_area_m2(length_m: float, width_m: float, height_m: float) -> float:
    return sum(per_pack_face_areas_m2(length_m, width_m, height_m).values())


def pack_volume_m3_per_pack(fleet_capacity_wh: float, n_packs: int, rho_wh_per_m3: float) -> float:
    """Per-pack volume V = (C_fleet/n_packs) / pack_volumetric_energy_density."""
    if n_packs <= 0 or rho_wh_per_m3 <= 0:
        raise ConfigError("n_packs and pack_volumetric_energy_density_wh_per_m3 must be positive")
    return (fleet_capacity_wh / n_packs) / rho_wh_per_m3


def box_dims_from_volume(
    ref_length_m: float, ref_width_m: float, ref_height_m: float, volume_m3: float
) -> Tuple[float, float, float]:
    v_ref = ref_length_m * ref_width_m * ref_height_m
    if v_ref <= 0 or volume_m3 <= 0:
        raise ConfigError("Reference box dims and volume must be positive")
    scale = (volume_m3 / v_ref) ** (1.0 / 3.0)
    return ref_length_m * scale, ref_width_m * scale, ref_height_m * scale


def distributed_pack_radiation_loss_w(
    length_m: float,
    width_m: float,
    height_m: float,
    emittance: float,
    t_box_k: float,
    t_sky_k: float,
    t_ground_k: float,
    f_sky_vert: float,
    f_ground_vert: float,
    emittance_multiplier: float,
    sigma: float,
) -> Tuple[float, float, Dict[str, float]]:
    e_eff = emittance * emittance_multiplier
    areas = per_pack_face_areas_m2(length_m, width_m, height_m)
    q = 0.0
    q += face_radiation_w(e_eff, areas["vertical_sides"], t_box_k, t_sky_k, t_ground_k, f_sky_vert, f_ground_vert, sigma)
    q += face_radiation_w(e_eff, areas["top"], t_box_k, t_sky_k, t_ground_k, 1.0, 0.0, sigma)
    q += face_radiation_w(e_eff, areas["bottom"], t_box_k, t_sky_k, t_ground_k, 0.0, 1.0, sigma)
    total_a = sum(areas.values())
    return q, total_a, areas


def effective_sink_temperature_k(t_sky_k: float, t_ground_k: float, f_sky: float = 0.5, f_ground: float = 0.5) -> float:
    """Radiative sink T from sky/ground T^4 mix."""
    return (f_sky * t_sky_k**4 + f_ground * t_ground_k**4) ** 0.25


def radiator_area_for_reject_w(
    q_reject_w: float,
    emissivity: float,
    t_rad_k: float,
    t_sink_k: float,
    sigma: float = SIGMA_DEFAULT,
) -> float:
    denom = emissivity * sigma * (t_rad_k**4 - t_sink_k**4)
    if denom <= 0 or q_reject_w <= 0:
        return 0.0
    return q_reject_w / denom


def radiator_bare_and_deployed_area_m2(
    q_reject_w: float,
    emissivity: float,
    t_rad_k: float,
    t_sink_k: float,
    louver_area_factor: float,
    sigma: float = SIGMA_DEFAULT,
) -> Tuple[float, float]:
    """Bare fin area from heat load; deployed = Table 16 louver factor × bare."""
    bare = radiator_area_for_reject_w(q_reject_w, emissivity, t_rad_k, t_sink_k, sigma)
    return bare, bare * louver_area_factor


def radiator_mass_kg(area_deployed_m2: float, areal_mass_kg_per_m2: float) -> float:
    """Colozza 2020 — full radiator areal mass (Table 17 total, 12.3 kg/m² deployed)."""
    return area_deployed_m2 * areal_mass_kg_per_m2


def radiator_night_leak_w(
    eps_closed: float,
    area_deployed_m2: float,
    t_box_k: float,
    t_sink_k: float,
    sigma: float = SIGMA_DEFAULT,
) -> float:
    """Closed louvers: ε σ A (T_box⁴ − T_sink⁴)."""
    if area_deployed_m2 <= 0 or eps_closed <= 0:
        return 0.0
    dt4 = max(0.0, t_box_k**4 - t_sink_k**4)
    return eps_closed * sigma * area_deployed_m2 * dt4


def validate_radiator_temperature(cfg: Dict[str, Any]) -> float:
    t_hold = param_value(cfg, "battery", "box_target_temperature_k")
    t_rad = param_value(cfg, "radiator", "radiator_temperature_k")
    if t_rad is None or t_hold is None:
        raise ConfigError("radiator.radiator_temperature_k and battery.box_target_temperature_k are required")
    if t_rad > t_hold:
        raise ConfigError(
            f"radiator_temperature_k ({t_rad:.2f} K) must be ≤ box_target_temperature_k ({t_hold:.2f} K) "
            "for a passive radiator (no heat pump modelled)"
        )
    return float(t_rad)


def wake_solar_panel_area_m2(
    p_wake_w: float, solar_constant_w_m2: float, panel_efficiency: float, incidence_cosine: float
) -> float:
    denom = solar_constant_w_m2 * panel_efficiency * incidence_cosine
    if denom <= 0:
        raise ConfigError("wake_up panel inputs must be positive")
    return p_wake_w / denom


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
    n_packs: int = 1
    q_per_pack_w: float = 0.0
    q_radiator_night_leak_w: float = 0.0
    radiator_area_per_pack_m2: float = 0.0
    radiator_mass_per_pack_kg: float = 0.0
    radiator_area_total_m2: float = 0.0
    radiator_mass_total_kg: float = 0.0
    radiator_bare_area_per_pack_m2: float = 0.0
    box_length_m: float = 0.0
    box_width_m: float = 0.0
    box_height_m: float = 0.0
    pack_volume_m3: float = 0.0


def leg_perimeter_m(cfg: Dict[str, Any]) -> float:
    p = param_value(cfg, "lander_legs", "leg_perimeter_m")
    if p is not None and p > 0:
        return float(p)
    raise ConfigError("lander_legs.leg_perimeter_m must be set (TODO-luke — tube/hollow strut wetted perimeter).")


def rtg_module_enabled(cfg: Dict[str, Any]) -> bool:
    block = cfg.get("rtg", {})
    if "enabled" in block:
        return bool(param_value(cfg, "rtg", "enabled"))
    return False


def compute_thermal_loss(
    cfg: Dict[str, Any],
    emittance: Optional[float] = None,
    k_leg: Optional[float] = None,
    t_box_k: Optional[float] = None,
    n_packs_override: Optional[int] = None,
    box_dims_override: Optional[Tuple[float, float, float]] = None,
    q_radiator_reject_per_pack_w: float = 0.0,
    fleet_capacity_wh: Optional[float] = None,
    radiator_operating: bool = True,
    radiator_deployed_area_m2_per_pack: Optional[float] = None,
    radiator_stuck_open: bool = False,
) -> ThermalLoss:
    t_box = t_box_k if t_box_k is not None else param_value(cfg, "battery", "box_target_temperature_k")
    t_sky = param_value(cfg, "thermal_environment", "deep_space_sink_k")
    t_ground = param_value(cfg, "thermal_environment", "night_surface_k")
    k_reg_surf = param_value(cfg, "thermal_environment", "regolith_k_surface_w_per_mk")
    k_reg_depth = param_value(cfg, "thermal_environment", "regolith_k_depth_w_per_mk")
    h_contact = param_value(cfg, "thermal_environment", "footpad_contact_conductance_w_per_m2k")

    e_box = emittance if emittance is not None else param_value(cfg, "radiation", "box_effective_emittance")
    e_mult = param_value(cfg, "radiation", "penetration_seam_emittance_multiplier") or 1.0
    sigma = param_value(cfg, "physics", "stefan_boltzmann_w_per_m2k4") or SIGMA_DEFAULT
    f_sky = param_value(cfg, "geometry", "view_factor_sky_vertical") or 0.5
    f_g = param_value(cfg, "geometry", "view_factor_ground_vertical") or 0.5

    layout = param_value(cfg, "layout", "model") or "distributed_packs"
    n_packs = n_packs_override if n_packs_override is not None else int(param_value(cfg, "geometry", "n_packs") or 1)
    ref_l = param_value(cfg, "geometry", "box_length_m")
    ref_w = param_value(cfg, "geometry", "box_width_m")
    ref_h = param_value(cfg, "geometry", "box_height_m")

    n_legs = param_value(cfg, "lander_legs", "n_legs")
    k_leg = k_leg if k_leg is not None else param_value(cfg, "lander_legs", "leg_thermal_conductivity_w_per_mk")
    a_cross = param_value(cfg, "lander_legs", "leg_cross_section_m2")
    leg_len = param_value(cfg, "lander_legs", "leg_length_m")
    leg_eps = param_value(cfg, "lander_legs", "leg_surface_emissivity")
    footpad_a = param_value(cfg, "lander_legs", "footpad_area_m2")
    n_seg = param_value(cfg, "lander_legs", "leg_fin_segments") or 12
    perim = leg_perimeter_m(cfg)
    passthrough = param_value(cfg, "losses", "passthrough_w") or 0.0
    rho_vol = param_value(cfg, "battery", "pack_volumetric_energy_density_wh_per_m3")

    if layout == "ring_rtg":
        n_boxes = param_value(cfg, "geometry", "n_battery_boxes")
        ring_r = param_value(cfg, "geometry", "ring_radius_m")
        bottom_to = param_value(cfg, "geometry", "bottom_radiates_to") or "ground"
        t_deck = param_value(cfg, "thermal_environment", "lander_deck_temperature_k")
        if bottom_to == "lander_deck" and t_deck is None:
            raise ConfigError("bottom_radiates_to=lander_deck requires thermal_environment.lander_deck_temperature_k")
        t_bottom_sink = t_deck if bottom_to == "lander_deck" else t_ground
        q_rad, area, _ = box_radiation_loss_w(
            n_boxes, ref_l, ref_w, ref_h, ring_r, e_box, t_box, t_sky, t_ground, t_bottom_sink,
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
        return ThermalLoss(
            q_box_rad_w=q_rad,
            q_leg_w=q_leg_surf,
            q_leg_at_surface_k_w=q_leg_surf,
            q_leg_at_depth_k_w=q_leg_depth,
            t_leg_foot_k=t_foot,
            q_passthrough_w=passthrough,
            q_total_w=q_total_surf,
            q_total_at_depth_k_w=q_rad + q_leg_depth + passthrough,
            area_radiating_m2=area,
            n_packs=n_boxes or 1,
        )

    pack_vol = 0.0
    if box_dims_override:
        box_l, box_w, box_h = box_dims_override
    elif fleet_capacity_wh is not None and rho_vol is not None and rho_vol > 0:
        pack_vol = pack_volume_m3_per_pack(fleet_capacity_wh, n_packs, rho_vol)
        box_l, box_w, box_h = box_dims_from_volume(ref_l, ref_w, ref_h, pack_vol)
    else:
        if rho_vol is None or rho_vol <= 0:
            raise ConfigError("battery.pack_volumetric_energy_density_wh_per_m3 required for distributed sizing")
        raise ConfigError("fleet_capacity_wh required to size pack box from volumetric energy density")

    t_rad = validate_radiator_temperature(cfg)
    e_rad = param_value(cfg, "radiator", "radiator_emissivity")
    areal_mass = param_value(cfg, "radiator", "radiator_areal_mass_kg_per_m2")
    louver = param_value(cfg, "radiator", "louver_area_multiplier")
    eps_closed = param_value(cfg, "radiator", "radiator_closed_emissivity")
    if e_rad is None or areal_mass is None or louver is None or eps_closed is None:
        raise ConfigError("Complete radiator.* block required (no silent defaults)")

    q_rad_1, area_1, _ = distributed_pack_radiation_loss_w(
        box_l, box_w, box_h, e_box, t_box, t_sky, t_ground, f_sky, f_g, e_mult, sigma
    )
    q_leg_surf_1, t_foot, _ = legs_total_loss_w(
        n_legs, k_leg, a_cross, perim, leg_len, leg_eps, t_box, t_sky, t_ground, t_ground,
        footpad_a, h_contact, k_reg_surf, f_sky, f_g, n_seg, sigma,
    )
    q_leg_depth_1, _, _ = legs_total_loss_w(
        n_legs, k_leg, a_cross, perim, leg_len, leg_eps, t_box, t_sky, t_ground, t_ground,
        footpad_a, h_contact, k_reg_depth, f_sky, f_g, n_seg, sigma,
    )
    t_sink = effective_sink_temperature_k(t_sky, t_ground, f_sky, f_g)
    if radiator_deployed_area_m2_per_pack is not None:
        area_deployed = max(0.0, radiator_deployed_area_m2_per_pack)
        _bare = area_deployed / louver if louver > 0 else 0.0
    else:
        _bare, area_deployed = radiator_bare_and_deployed_area_m2(
            q_radiator_reject_per_pack_w, e_rad, t_rad, t_sink, louver, sigma
        )
    m_rad_pp = radiator_mass_kg(area_deployed, areal_mass)
    leak_per_pack = (
        0.0
        if radiator_operating
        else radiator_night_leak_w(eps_closed, area_deployed, t_box, t_sink, sigma)
    )
    q_stuck_pp = 0.0
    if radiator_stuck_open and _bare > 0:
        q_stuck_pp = e_rad * sigma * _bare * max(0.0, t_box**4 - t_sink**4)
    passthrough_pp = passthrough / n_packs if n_packs > 0 else passthrough
    q_pp = q_rad_1 + q_leg_surf_1 + passthrough_pp + leak_per_pack + q_stuck_pp

    q_rad_fleet = q_rad_1 * n_packs
    q_leg_fleet = q_leg_surf_1 * n_packs
    q_leak_fleet = leak_per_pack * n_packs
    q_total = q_pp * n_packs

    return ThermalLoss(
        q_box_rad_w=q_rad_fleet,
        q_leg_w=q_leg_fleet,
        q_leg_at_surface_k_w=q_leg_fleet,
        q_leg_at_depth_k_w=q_leg_depth_1 * n_packs,
        t_leg_foot_k=t_foot,
        q_passthrough_w=passthrough,
        q_total_w=q_total,
        q_total_at_depth_k_w=q_rad_fleet + q_leg_depth_1 * n_packs + passthrough,
        area_radiating_m2=area_1 * n_packs,
        n_packs=n_packs,
        q_per_pack_w=q_pp,
        q_radiator_night_leak_w=q_leak_fleet,
        radiator_area_per_pack_m2=area_deployed,
        radiator_bare_area_per_pack_m2=_bare,
        radiator_mass_per_pack_kg=m_rad_pp,
        radiator_area_total_m2=area_deployed * n_packs,
        radiator_mass_total_kg=m_rad_pp * n_packs,
        box_length_m=box_l,
        box_width_m=box_w,
        box_height_m=box_h,
        pack_volume_m3=pack_vol,
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


def thermal_q_loss_at_box_t(
    cfg: Dict[str, Any],
    t_box_k: float,
    fleet_capacity_wh: Optional[float] = None,
    q_excess_per_pack_w: float = 0.0,
) -> float:
    th = compute_thermal_loss(
        cfg,
        t_box_k=t_box_k,
        fleet_capacity_wh=fleet_capacity_wh,
        q_radiator_reject_per_pack_w=q_excess_per_pack_w,
        radiator_operating=False,
    )
    n = max(1, th.n_packs)
    return th.q_per_pack_w if th.q_per_pack_w > 0 else th.q_total_w / n


def build_q_loss_temperature_lut(
    cfg: Dict[str, Any],
    t_min_k: float = 40.0,
    t_max_k: float = 280.0,
    n_points: int = 50,
    fleet_capacity_wh: Optional[float] = None,
    q_excess_per_pack_w: float = 0.0,
) -> Tuple[List[float], List[float]]:
    """Precompute Q_loss(T) for fast lumped transient integration."""
    import numpy as np

    temps = [float(x) for x in np.linspace(t_min_k, t_max_k, max(5, n_points))]
    q_vals = [
        thermal_q_loss_at_box_t(
            cfg, t, fleet_capacity_wh=fleet_capacity_wh, q_excess_per_pack_w=q_excess_per_pack_w
        )
        for t in temps
    ]
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
    fleet_capacity_wh: Optional[float] = None,
    q_excess_per_pack_w: float = 0.0,
    heater_from_pack: bool = True,
) -> Dict[str, Any]:
    """Lumped capacitance with Q_loss(T). Heater from pack draws discharge loss; solar wake does not."""
    if mass_kg <= 0 or cp_j_kgk <= 0 or duration_h <= 0:
        raise ValueError("mass, cp, and duration must be positive")
    mc = mass_kg * cp_j_kgk
    q_int_load, _ = pick_internal_heat(internal_waste_heat_w(p_load_w, eta), eta_definition)
    if heater_from_pack and p_heater_w > 0:
        q_int_heat, _ = pick_internal_heat(internal_waste_heat_w(p_heater_w, eta), eta_definition)
    else:
        q_int_heat = 0.0
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
            q_loss = thermal_q_loss_at_box_t(
                cfg, temp, fleet_capacity_wh=fleet_capacity_wh, q_excess_per_pack_w=q_excess_per_pack_w
            )
        if heater_from_pack:
            q_in = q_int_load + q_int_heat + p_heater_w
        else:
            q_in = q_int_load + p_heater_w
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


def solve_dawn_warmup_solar_w(
    cfg: Dict[str, Any],
    mass_kg: float,
    cp_j_kgk: float,
    t_start_k: float,
    t_target_k: float,
    warm_up_h: float,
    dt_s: float = 120.0,
    q_loss_lut: Optional[Tuple[List[float], List[float]]] = None,
    fleet_capacity_wh: Optional[float] = None,
    q_excess_per_pack_w: float = 0.0,
) -> Dict[str, float]:
    """Dedicated solar wake panel: P_in = P_heater with no battery discharge loss (η not applied)."""
    if warm_up_h <= 0 or t_target_k <= t_start_k:
        return {"p_heater_w": 0.0, "energy_wh": 0.0, "energy_warm_wh": 0.0}

    def temp_at_end(p_h: float) -> float:
        coast = integrate_lumped_thermal_coast(
            cfg,
            mass_kg,
            cp_j_kgk,
            t_start_k,
            warm_up_h,
            p_heater_w=p_h,
            dt_s=dt_s,
            q_loss_lut=q_loss_lut,
            fleet_capacity_wh=fleet_capacity_wh,
            q_excess_per_pack_w=q_excess_per_pack_w,
            heater_from_pack=False,
        )
        return coast["t_final_k"]

    lo, hi = 0.0, max(
        500.0, thermal_q_loss_at_box_t(cfg, t_start_k, fleet_capacity_wh, q_excess_per_pack_w) * 3.0
    )
    for _ in range(8):
        if temp_at_end(hi) >= t_target_k:
            break
        hi *= 2.0
    else:
        raise ConfigError("dawn warm-up: could not bracket solar heater power — extend warm_up_h or check inputs")
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
        dt_s=dt_s,
        q_loss_lut=q_loss_lut,
        fleet_capacity_wh=fleet_capacity_wh,
        q_excess_per_pack_w=q_excess_per_pack_w,
        heater_from_pack=False,
    )
    e_wh = p_solve * warm_up_h
    return {"p_heater_w": p_solve, "energy_wh": e_wh, "energy_warm_wh": e_wh, "t_final_k": coast["t_final_k"]}


def size_wake_solar_panel(cfg: Dict[str, Any], p_wake_w: float) -> Tuple[float, float]:
    s = param_value(cfg, "wake_up", "solar_constant_w_per_m2")
    eff = param_value(cfg, "wake_up", "panel_efficiency")
    cos_i = param_value(cfg, "wake_up", "sun_incidence_cosine")
    m_area = param_value(cfg, "wake_up", "panel_areal_mass_kg_per_m2")
    area = wake_solar_panel_area_m2(p_wake_w, s, eff, cos_i)
    return area, area * m_area


@dataclass
class CaseResult:
    load_name: str
    load_w: float
    specific_energy_wh_kg: float
    case: str
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
    wake_panel_area_per_pack_m2: Optional[float] = None
    wake_panel_mass_per_pack_kg: Optional[float] = None
    wake_panel_area_fleet_m2: Optional[float] = None
    wake_panel_mass_fleet_kg: Optional[float] = None
    wake_p_per_pack_w: Optional[float] = None
    system_mass_kg: Optional[float] = None
    break_even_load_w: Optional[float] = None
    coast_stuck_open_t_final_k: Optional[float] = None
    coast_stuck_open_margin_lipo_k: Optional[float] = None
    louvers_stuck_below_lipo: Optional[bool] = None
    cold_margin_alert: Optional[bool] = None


def design_blockers(cfg: Dict[str, Any]) -> List[str]:
    """Same list validate_for_run requires (without raising)."""
    return blocking_missing(cfg)


def break_even_load_w(q_thermal_out_w: float, eta_discharge: float) -> float:
    """Load where Q_internal equals Q_loss + closed-radiator leak (louvers shut)."""
    denom = (1.0 / eta_discharge) - 1.0
    if denom <= 0:
        return float("inf")
    return q_thermal_out_w / denom


def lipo_margin_threshold_k(cfg: Dict[str, Any]) -> Optional[float]:
    t = param_value(cfg, "battery", "lipo_margin_threshold_k")
    return float(t) if t is not None else None


def build_q_loss_stuck_open_lut(
    cfg: Dict[str, Any],
    fleet_capacity_wh: float,
    radiator_deployed_m2_per_pack: float,
    radiator_bare_m2_per_pack: float,
    n_points: int = 60,
) -> Tuple[List[float], List[float]]:
    import numpy as np

    temps = [float(x) for x in np.linspace(40.0, 290.0, max(5, n_points))]
    q_vals = [
        thermal_q_per_pack_stuck_open_radiator(
            cfg, t, fleet_capacity_wh, radiator_deployed_m2_per_pack, radiator_bare_m2_per_pack
        )
        for t in temps
    ]
    return temps, q_vals


def thermal_q_per_pack_stuck_open_radiator(
    cfg: Dict[str, Any],
    t_box_k: float,
    fleet_capacity_wh: Optional[float],
    radiator_deployed_m2_per_pack: float,
    radiator_bare_m2_per_pack: float,
) -> float:
    """Per-pack Q_loss with louvers stuck open: box + legs + ε σ A_bare (T⁴ − T_sink⁴)."""
    th = compute_thermal_loss(
        cfg,
        t_box_k=t_box_k,
        fleet_capacity_wh=fleet_capacity_wh,
        radiator_operating=True,
        radiator_deployed_area_m2_per_pack=radiator_deployed_m2_per_pack,
        q_radiator_reject_per_pack_w=0.0,
        radiator_stuck_open=False,
    )
    e_rad = param_value(cfg, "radiator", "radiator_emissivity")
    sigma = param_value(cfg, "physics", "stefan_boltzmann_w_per_m2k4") or SIGMA_DEFAULT
    t_sky = param_value(cfg, "thermal_environment", "deep_space_sink_k")
    t_ground = param_value(cfg, "thermal_environment", "night_surface_k")
    f_sky = param_value(cfg, "geometry", "view_factor_sky_vertical") or 0.5
    f_g = param_value(cfg, "geometry", "view_factor_ground_vertical") or 0.5
    t_sink = effective_sink_temperature_k(t_sky, t_ground, f_sky, f_g)
    q_rad_open = e_rad * sigma * radiator_bare_m2_per_pack * max(0.0, t_box_k**4 - t_sink**4)
    return th.q_per_pack_w + q_rad_open


def integrate_louvers_stuck_open_coast(
    cfg: Dict[str, Any],
    mass_per_pack_kg: float,
    cp_j_kgk: float,
    t_start_k: float,
    duration_h: float,
    p_load_fleet_w: float,
    eta: float,
    eta_definition: str,
    fleet_capacity_wh: float,
    radiator_deployed_m2_per_pack: float,
    radiator_bare_m2_per_pack: float,
    *,
    dt_s: float = 120.0,
    lipo_limit_k: Optional[float] = None,
) -> Dict[str, Any]:
    """Per-pack coast with louvers stuck open (bare radiator area); T-dependent box, legs, radiative loss."""
    n_packs = max(1, int(param_value(cfg, "geometry", "n_packs") or 1))
    q_int_fleet, _ = pick_internal_heat(internal_waste_heat_w(p_load_fleet_w, eta), eta_definition)
    mc = mass_per_pack_kg * cp_j_kgk
    q_lut = build_q_loss_stuck_open_lut(
        cfg, fleet_capacity_wh, radiator_deployed_m2_per_pack, radiator_bare_m2_per_pack
    )
    t = 0.0
    t_end_s = duration_h * 3600.0
    temp = t_start_k
    energy_out_j = 0.0
    time_to_lipo_h: Optional[float] = None
    while t < t_end_s - 1e-9:
        step = min(dt_s, t_end_s - t)
        q_loss_pp = q_loss_from_lut(temp, q_lut[0], q_lut[1])
        q_int_pp = q_int_fleet / n_packs
        q_net_out_pp = q_loss_pp - q_int_pp
        energy_out_j += q_net_out_pp * n_packs * step
        temp -= q_net_out_pp * step / mc
        t += step
        if lipo_limit_k is not None and time_to_lipo_h is None and temp <= lipo_limit_k:
            time_to_lipo_h = t / 3600.0
    return {
        "t_final_k": temp,
        "delta_t_k": temp - t_start_k,
        "time_to_lipo_h": time_to_lipo_h,
        "margin_lipo_k": (temp - lipo_limit_k) if lipo_limit_k is not None else None,
        "energy_net_out_kwh": max(0.0, energy_out_j / 3.6e6),
    }


def solve_case(
    load_name: str,
    load_w: float,
    specific_energy: float,
    cfg: Dict[str, Any],
    case_branch: str = "primary",
    emittance: Optional[float] = None,
    k_leg: Optional[float] = None,
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
    rtg_on = rtg_module_enabled(cfg)
    coupling = param_value(cfg, "rtg", "coupling_fraction") if rtg_on else None
    rtg_counts: List[int] = (param_value(cfg, "rtg", "count_list") or []) if rtg_on else []
    q_rtg_fixed = param_value(cfg, "rtg", "thermal_output_w") if rtg_on else None

    q_int_map = internal_waste_heat_w(load_w, eta)
    q_internal, q_note = pick_internal_heat(q_int_map, eta_def)

    p_heater = 0.0
    iterations = 0
    thermal_cfg = cfg
    iterate = mode == "fixed_rtg"

    for loop_i in range(max_iter if iterate else 1):
        iterations = loop_i + 1
        battery = size_battery_pack(
            load_w, p_heater, t_dark, dod, eta_dis, specific_energy, packaging, bus_v, cell_v, cell_ah
        )
        cap_wh = battery.capacity_wh
        thermal = compute_thermal_loss(
            thermal_cfg,
            emittance=emittance,
            k_leg=k_leg,
            fleet_capacity_wh=cap_wh,
            radiator_operating=True,
        )
        excess_pre = max(0.0, q_internal - thermal.q_total_w)
        n_p = max(1, thermal.n_packs)
        thermal = compute_thermal_loss(
            thermal_cfg,
            emittance=emittance,
            k_leg=k_leg,
            q_radiator_reject_per_pack_w=excess_pre / n_p,
            fleet_capacity_wh=cap_wh,
            radiator_operating=True,
        )
        if mode == "fixed_rtg" and rtg_on:
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

    if not rtg_on:
        q_rtg_total = None
        q_msg = "RTG module disabled — excess rejected via per-pack radiators"
        excess = max(0.0, q_internal - thermal.q_total_w)
        per_unit: Dict[int, float] = {}
    elif mode == "fixed_rtg" and q_rtg_fixed is not None:
        q_rtg_total = float(q_rtg_fixed)
        q_msg = "fixed_rtg mode — using rtg.thermal_output_w"
        excess = max(0.0, q_internal - thermal.q_total_w)
        per_unit = {n: q_rtg_total / n for n in rtg_counts if n > 0}
    elif coupling is None:
        q_rtg_total = None
        q_msg = "RTG need cannot be computed until rtg.coupling_fraction is chosen (Q_loss reported)."
        excess = max(0.0, q_internal - thermal.q_total_w)
        per_unit = {}
    else:
        q_rtg_total, excess = net_rtg_need_w(thermal.q_total_w, q_internal, coupling)
        q_msg = "solve_rtg: Q_RTG = max(0,Q_loss-Q_internal)/coupling"
        per_unit = {n: q_rtg_total / n for n in rtg_counts if n > 0 and q_rtg_total is not None}

    leg_mass = 0.0
    if cfg.get("lander_legs", {}).get("leg_structure_mass_kg_per_pack") is not None:
        leg_mass = float(param_value(cfg, "lander_legs", "leg_structure_mass_kg_per_pack") or 0.0)
    system_mass = battery.mass_kg + thermal.radiator_mass_total_kg + leg_mass * max(1, thermal.n_packs)

    mass_for_transient = battery.mass_kg
    q_net_no_rtg = thermal.q_total_w - q_internal
    dT = lumped_transient_delta_t_k(q_net_no_rtg, mass_for_transient, cp, t_dark)
    p_be: Optional[float] = None
    if case_branch == "primary":
        th_closed = compute_thermal_loss(
            thermal_cfg,
            emittance=emittance,
            k_leg=k_leg,
            fleet_capacity_wh=cap_wh,
            radiator_operating=False,
            radiator_deployed_area_m2_per_pack=thermal.radiator_area_per_pack_m2,
            q_radiator_reject_per_pack_w=0.0,
        )
        p_be = break_even_load_w(th_closed.q_total_w, eta_dis)
    below_lipo = (t_box + dT < lipo_lim) if dT is not None else None
    twarn = None
    if dT is not None:
        if t_box + dT < 0:
            twarn = f"nonphysical transient: T_final={t_box + dT:.1f} K (< 0)"
        elif below_lipo:
            twarn = f"transient below LiPo limit ({lipo_lim} K)"

    rad_couple = None
    if rtg_on and param_value(cfg, "layout", "model") == "ring_rtg":
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
        case=case_branch,
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
        system_mass_kg=system_mass,
        break_even_load_w=p_be,
    )


def solve_cold_shutdown_case(
    cfg: Dict[str, Any],
    primary: CaseResult,
    *,
    dt_s: float = 120.0,
) -> CaseResult:
    """Zero load backup: per-pack coast through night with Q_loss(T), dawn warm-up per pack."""
    validate_for_run(cfg)
    t_dark = param_value(cfg, "night", "t_dark_h")
    eta = battery_efficiency_value(cfg)
    eta_def = param_value(cfg, "battery", "eta_definition")
    cp = param_value(cfg, "battery", "pack_specific_heat_j_per_kgk")
    lipo_lim = param_value(cfg, "battery", "lipo_cold_limit_k")
    t_box = param_value(cfg, "battery", "box_target_temperature_k")
    t_min_charge = param_value(cfg, "battery", "minimum_charge_temperature_k")
    warm_h = param_value(cfg, "wake_up", "warm_up_h")
    if cp is None or cp <= 0:
        raise ConfigError("cold_shutdown transient requires battery.pack_specific_heat_j_per_kgk")
    if warm_h is None or warm_h <= 0:
        raise ConfigError("wake_up.warm_up_h required for dawn warm-up")

    cap_wh = primary.battery.capacity_wh
    n_packs = max(1, primary.thermal.n_packs)
    mass_per_pack = primary.battery.mass_kg / n_packs
    q_ex_pp = max(0.0, primary.q_excess_w) / n_packs
    lut = build_q_loss_temperature_lut(
        cfg,
        t_min_k=min(lipo_lim or 40, t_box) - 10,
        t_max_k=t_box + 5,
        fleet_capacity_wh=cap_wh,
        q_excess_per_pack_w=q_ex_pp,
    )
    coast = integrate_lumped_thermal_coast(
        cfg,
        mass_per_pack,
        cp,
        t_box,
        t_dark,
        p_load_w=0.0,
        eta=eta,
        eta_definition=eta_def,
        dt_s=dt_s,
        lipo_limit_k=lipo_lim,
        q_loss_lut=lut,
        fleet_capacity_wh=cap_wh,
    )
    t_final = coast["t_final_k"]
    warmup_target = t_box
    warmup = solve_dawn_warmup_solar_w(
        cfg,
        mass_per_pack,
        cp,
        t_final,
        warmup_target,
        warm_h,
        dt_s=dt_s,
        q_loss_lut=lut,
        fleet_capacity_wh=cap_wh,
        q_excess_per_pack_w=q_ex_pp,
    )
    panel_a, panel_m = size_wake_solar_panel(cfg, warmup["p_heater_w"])

    thermal_hold = compute_thermal_loss(cfg, fleet_capacity_wh=cap_wh)
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
        mass_kg=primary.battery.mass_kg,
        n_series=battery.n_series,
        n_parallel=battery.n_parallel,
        energy_per_string_wh=battery.energy_per_string_wh,
        bus_v=battery.bus_v,
        cell_v=battery.cell_v,
        cell_ah=battery.cell_ah,
    )
    dT = coast["t_final_k"] - t_box
    stuck_coast = integrate_louvers_stuck_open_coast(
        cfg,
        mass_per_pack,
        cp,
        t_box,
        t_dark,
        0.0,
        eta,
        eta_def,
        cap_wh,
        primary.thermal.radiator_area_per_pack_m2,
        primary.thermal.radiator_bare_area_per_pack_m2,
        dt_s=dt_s,
        lipo_limit_k=lipo_lim,
    )
    margin_thr = lipo_margin_threshold_k(cfg)
    margin_alert = (
        coast["margin_lipo_k"] is not None
        and margin_thr is not None
        and coast["margin_lipo_k"] < margin_thr
    )
    note = (
        "Energy from solar wake-up circuit before charge is allowed "
        "(charging blocked below minimum_charge_temperature_k)."
    )
    return CaseResult(
        load_name="cold_shutdown_0W",
        load_w=0.0,
        specific_energy_wh_kg=primary.specific_energy_wh_kg,
        case="cold_shutdown",
        battery=battery,
        thermal=thermal_hold,
        q_internal_w=q_internal,
        q_internal_note=q_note,
        q_internal_both=q_int_map,
        q_excess_w=0.0,
        q_rtg_total_w=None,
        q_rtg_message="cold_shutdown per pack — no RTG (radiator-based 5 kW design)",
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
        dawn_warmup_energy_wh=warmup["energy_wh"] * n_packs,
        dawn_warmup_note=note
        + f" Solar wake: P_pack={warmup['p_heater_w']:.1f} W, panel {panel_a:.2f} m²/pack; fleet ×{n_packs}",
        wake_panel_area_per_pack_m2=panel_a,
        wake_panel_mass_per_pack_kg=panel_m,
        wake_panel_area_fleet_m2=panel_a * n_packs,
        wake_panel_mass_fleet_kg=panel_m * n_packs,
        wake_p_per_pack_w=warmup["p_heater_w"],
        system_mass_kg=(primary.system_mass_kg or 0) + panel_m * n_packs,
        cold_margin_alert=margin_alert,
        coast_stuck_open_t_final_k=stuck_coast["t_final_k"],
        coast_stuck_open_margin_lipo_k=stuck_coast["margin_lipo_k"],
        louvers_stuck_below_lipo=stuck_coast["margin_lipo_k"] is not None and stuck_coast["margin_lipo_k"] < 0,
    )


def todo_luke_list(cfg: Dict[str, Any]) -> List[str]:
    rows = []
    for row in flatten_inputs(cfg):
        if row["owner"] == "TODO-luke":
            suffix = " (unset)" if row["value"] == "(unset)" else ""
            rows.append(f"{row['path']}: {row['value']} {row['units']} — {row['source']}{suffix}")
    return rows


def placeholder_list(cfg: Dict[str, Any]) -> List[str]:
    rows = []
    for row in flatten_inputs(cfg):
        if row["owner"] == "placeholder":
            rows.append(f"{row['path']}: {row['value']} {row['units']} — {row['source']}")
    return rows


def format_results_table(results: List[CaseResult], coupling_set: bool, cfg: Optional[Dict[str, Any]] = None) -> str:
    lines = ["", "=" * 100, "LUNAR BASE DISTRIBUTED PACK + RADIATOR SIZER", "=" * 100]
    if not coupling_set:
        lines.append("NOTE: RTG module disabled or coupling unset — per-pack radiators reject excess heat.")
    for r in results:
        lines.append(
            f"\n--- {r.load_name} [{r.case}] @ {r.specific_energy_wh_kg} Wh/kg "
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
        lines.append(f"  Pack mass     = {b.mass_kg:.1f} kg (cells only)")
        if r.system_mass_kg is not None:
            lines.append(f"  System mass   = {r.system_mass_kg:.1f} kg (+ radiators)")
        lines.append(f"  N_packs       = {r.thermal.n_packs}")
        lines.append(f"  N_series      = {b.n_series}")
        th = r.thermal
        lines.append(
            f"  Per-pack box  = {th.box_length_m:.3f}×{th.box_width_m:.3f}×{th.box_height_m:.3f} m; "
            f"Q_loss/pack ≈ {th.q_per_pack_w:.1f} W"
        )
        lines.append(
            f"  Q_loss fleet  = {r.thermal.q_total_w:.1f} W "
            f"(box {r.thermal.q_box_rad_w:.1f}, legs {r.thermal.q_leg_w:.1f}, leak {r.thermal.q_radiator_night_leak_w:.1f})"
        )
        if th.radiator_area_per_pack_m2 > 0:
            lines.append(
                f"  Radiator/pack = {th.radiator_area_per_pack_m2:.3f} m² deployed "
                f"({th.radiator_mass_per_pack_kg:.2f} kg); bare {th.radiator_bare_area_per_pack_m2:.3f} m²"
            )
        if r.wake_panel_area_per_pack_m2:
            lines.append(
                f"  Wake solar/pack = {r.wake_panel_area_per_pack_m2:.2f} m² "
                f"({r.wake_panel_mass_per_pack_kg:.1f} kg), P≈{r.wake_p_per_pack_w:.0f} W"
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
                f"{r.battery.t_dark_h:.0f} h night; lumped ΔT at hold ≈ {d_t:.1f} K (radiator rejection, no RTG)"
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
        if r.transient_delta_t_k is not None and r.case == "primary":
            lines.append(f"  Transient ΔT (passive coast, no RTG) ≈ {r.transient_delta_t_k:.2f} K")
        if r.case == "cold_shutdown" and r.coast_t_final_k is not None:
            t0 = r.coast_t_final_k - (r.transient_delta_t_k or 0.0)
            lines.append(
                f"  Cold shutdown coast: {t0:.2f} K → {r.coast_t_final_k:.2f} K over {r.battery.t_dark_h:.0f} h; "
                f"energy out ≈ {r.coast_energy_out_kwh:.2f} kWh"
            )
            if r.coast_time_to_lipo_h is not None:
                lines.append(f"  Time to LiPo limit: {r.coast_time_to_lipo_h:.2f} h")
            elif r.coast_margin_lipo_k is not None:
                lines.append(f"  LiPo margin at dawn (louvers closed): {r.coast_margin_lipo_k:.2f} K")
            if r.coast_stuck_open_t_final_k is not None:
                breach = " — BELOW LiPo limit" if r.louvers_stuck_below_lipo else ""
                marg = r.coast_stuck_open_margin_lipo_k
                mg = f", LiPo margin {marg:.2f} K" if marg is not None else ""
                lines.append(
                    f"  Louvers-stuck-open cold coast: {t0:.2f} K → {r.coast_stuck_open_t_final_k:.2f} K "
                    f"(closed louvers → {r.coast_t_final_k:.2f} K){mg}{breach}"
                )
                lines.append(
                    "  Radiator must passively close (louvers or thermal switch) for cold shutdown — see README."
                )
            if r.dawn_warmup_p_heater_w is not None and r.dawn_warmup_target_k is not None:
                lines.append(
                    f"  Dawn warm-up → {r.dawn_warmup_target_k:.1f} K: "
                    f"P_heater≈{r.dawn_warmup_p_heater_w:.1f} W, E≈{r.dawn_warmup_energy_wh/1000:.2f} kWh"
                )
                if r.dawn_warmup_note:
                    lines.append(f"  {r.dawn_warmup_note}")
        if r.case == "primary" and r.break_even_load_w is not None:
            lines.append(
                f"  Part-load break-even (louvers closed): P_be ≈ {r.break_even_load_w/1000:.3f} kW fleet "
                f"— below this, packs cool even with louvers shut"
            )
        if r.case == "cold_shutdown" and r.coast_margin_lipo_k is not None:
            thr = lipo_margin_threshold_k(cfg) if cfg else None
            if thr is not None and r.cold_margin_alert:
                lines.append(
                    f"  ALERT: LiPo margin {r.coast_margin_lipo_k:.2f} K < threshold {thr:.1f} K"
                )
            if thr is None:
                lines.append("  LiPo margin threshold unset (TODO-luke) — no margin alert applied")
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
    results: List[CaseResult] = []
    for se in (se_low, se_high):
        prim = solve_case("primary_5000W", primary_w, se, cfg, case_branch="primary")
        results.append(prim)
        results.append(solve_cold_shutdown_case(cfg, prim))
    return results


def run_n_packs_sensitivity(
    cfg: Dict[str, Any], specific_energy: float = 200.0, n_list: Tuple[int, ...] = (1, 2, 4, 8, 16)
) -> List[Dict[str, Any]]:
    """Sweep pack count at fixed fleet load; box volume scales ∝ 1/n."""
    import copy

    primary_w = param_value(cfg, "loads", "primary_w")
    rows: List[Dict[str, Any]] = []
    for n in n_list:
        c = copy.deepcopy(cfg)
        c["geometry"]["n_packs"]["value"] = n
        r = solve_case("primary_5000W", primary_w, specific_energy, c, case_branch="primary")
        cs = solve_cold_shutdown_case(c, r)
        th_closed = compute_thermal_loss(
            c,
            fleet_capacity_wh=r.battery.capacity_wh,
            radiator_operating=False,
            radiator_deployed_area_m2_per_pack=r.thermal.radiator_area_per_pack_m2,
            q_radiator_reject_per_pack_w=0.0,
        )
        eta_dis = discharge_efficiency_for_sizing(
            battery_efficiency_value(c), param_value(c, "battery", "eta_definition")
        )
        p_be = break_even_load_w(th_closed.q_total_w, eta_dis)
        thr = lipo_margin_threshold_k(c)
        margin_k = cs.coast_margin_lipo_k
        sys_m = cs.system_mass_kg if cs.system_mass_kg else r.system_mass_kg
        rows.append(
            {
                "n_packs": n,
                "mass_kg": r.battery.mass_kg,
                "system_mass_kg": sys_m,
                "q_loss_fleet_w": r.thermal.q_total_w,
                "q_excess_fleet_w": r.q_excess_w,
                "q_leak_fleet_w": th_closed.q_radiator_night_leak_w,
                "rad_area_pp_m2": r.thermal.radiator_area_per_pack_m2,
                "rad_mass_pp_kg": r.thermal.radiator_mass_per_pack_kg,
                "rad_mass_fleet_kg": r.thermal.radiator_mass_total_kg,
                "panel_pp_m2": cs.wake_panel_area_per_pack_m2,
                "panel_fleet_m2": cs.wake_panel_area_fleet_m2,
                "warm_fleet_kwh": cs.dawn_warmup_energy_wh / 1000 if cs.dawn_warmup_energy_wh else None,
                "cold_tf_k": cs.coast_t_final_k,
                "cold_tf_stuck_k": cs.coast_stuck_open_t_final_k,
                "cold_margin_k": margin_k,
                "cold_stuck_margin_k": cs.coast_stuck_open_margin_lipo_k,
                "margin_alert": margin_k is not None and thr is not None and margin_k < thr,
                "stuck_margin_alert": cs.coast_stuck_open_margin_lipo_k is not None
                and cs.coast_stuck_open_margin_lipo_k < 0,
                "p_be_w": p_be,
            }
        )
    return rows


def format_n_packs_table(rows: List[Dict[str, Any]], cfg: Optional[Dict[str, Any]] = None) -> str:
    lines = [
        "",
        "=" * 100,
        "N_PACKS SENSITIVITY (5 kW fleet, 200 Wh/kg, V_pack = (C/n)/ρ_vol)",
        "=" * 100,
    ]
    thr = lipo_margin_threshold_k(cfg) if cfg else None
    alert_hdr = "!" if thr is not None else "-"
    lines.append(
        f"{'n':>3} {'sys/kg':>7} {'Qloss_f':>8} {'Qexc_f':>8} {'Qleak_f':>7} {'Pbe/kW':>7} "
        f"{'Arad_pp':>8} {'Radkg_pp':>8} {'Apan_pp':>8} {'Tf_c':>6} {'Tf_so':>6} {'dLiPo':>6} "
        f"{'dLiPo_so':>7} {'Warm_f':>7} {alert_hdr:>1} {'*':>1}"
    )
    if thr is None and cfg is not None:
        lines.append(
            "(fleet W/kWh unless _pp = per pack; LiPo margin threshold unset; "
            "* = stuck-open coast below LiPo limit)"
        )
    else:
        lines.append(
            "(fleet W/kWh unless _pp = per pack; ! = margin below threshold; "
            "* = stuck-open below LiPo limit)"
        )
    for row in rows:
        tf = f"{row['cold_tf_k']:.1f}" if row["cold_tf_k"] is not None else "—"
        tf_so = f"{row['cold_tf_stuck_k']:.1f}" if row.get("cold_tf_stuck_k") is not None else "—"
        dm = f"{row['cold_margin_k']:.1f}" if row.get("cold_margin_k") is not None else "—"
        dm_so = (
            f"{row['cold_stuck_margin_k']:.1f}"
            if row.get("cold_stuck_margin_k") is not None
            else "—"
        )
        wk = f"{row['warm_fleet_kwh']:.2f}" if row.get("warm_fleet_kwh") is not None else "—"
        flag = "!" if row.get("margin_alert") else ""
        stuck = "*" if row.get("stuck_margin_alert") else ""
        lines.append(
            f"{row['n_packs']:3d} {row['system_mass_kg']:7.0f} "
            f"{row['q_loss_fleet_w']:8.1f} {row['q_excess_fleet_w']:8.1f} "
            f"{row['q_leak_fleet_w']:7.1f} {row['p_be_w']/1000:7.2f} "
            f"{row['rad_area_pp_m2']:8.3f} {row['rad_mass_pp_kg']:8.2f} "
            f"{row['panel_pp_m2']:8.2f} {tf:>6} {tf_so:>6} {dm:>6} {dm_so:>7} {wk:>7} {flag:>1}{stuck:>1}"
        )
    return "\n".join(lines)


def run_sensitivity(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    loads = [("primary", param_value(cfg, "loads", "primary_w"))]
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


def render_n_pack_sweep_lines_on_figure(
    fig,
    sweep_lines: List[str],
    *,
    start_y: float = 0.98,
    sweep_fs: float = 7.5,
    dy: float = 0.0135,
    x_frac: float = 0.06,
) -> float:
    """Draw monospace sweep lines using figure coords (full page width). Returns final y."""
    y = start_y
    for line in sweep_lines:
        fig.text(
            x_frac,
            y,
            line,
            fontsize=sweep_fs,
            family="monospace",
            va="top",
            transform=fig.transFigure,
        )
        y -= dy
    return y


def build_n_pack_sweep_figure(sweep_lines: List[str]):
    """Build a single-page sweep figure (for tests and layout checks)."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.axis("off")
    ax.set_position([0, 0, 1, 1])
    render_n_pack_sweep_lines_on_figure(fig, sweep_lines)
    return fig


def figure_text_extents_px(fig) -> Tuple[float, List[Tuple[float, float, str]]]:
    """Return (page_width_px, [(x0, x1, text), ...]) for all Text artists after draw."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    w_px = fig.get_figwidth() * fig.dpi
    rows: List[Tuple[float, float, str]] = []
    import matplotlib.text as mtext

    for artist in fig.findobj(mtext.Text):
        text = (artist.get_text() or "").strip()
        if not text:
            continue
        bbox = artist.get_window_extent(renderer)
        rows.append((float(bbox.x0), float(bbox.x1), artist.get_text() or ""))
    return w_px, rows


def write_report_pdf(
    path: Path,
    cfg: Dict[str, Any],
    results: List[CaseResult],
    sensitivity: List[Dict[str, Any]],
    todos: List[str],
    n_pack_rows: Optional[List[Dict[str, Any]]] = None,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    coupling_set = rtg_module_enabled(cfg) and param_value(cfg, "rtg", "coupling_fraction") is not None

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
                f"{r.load_name}/{r.case} @ {r.specific_energy_wh_kg} Wh/kg\n"
                f" mass={r.battery.mass_kg:.0f}kg Q_int={r.q_internal_w:.0f}W Q_loss={r.thermal.q_total_w:.0f}W"
            )
            if r.q_rtg_total_w is not None:
                block += f" Q_RTG={r.q_rtg_total_w:.0f}W"
            if r.q_excess_w > 0:
                block += f" EXCESS={r.q_excess_w:.0f}W"
            if r.transient_delta_t_k is not None:
                block += f" dT={r.transient_delta_t_k:.1f}K"
            if r.case == "cold_shutdown" and r.coast_t_final_k is not None:
                block += f" Tf_closed={r.coast_t_final_k:.1f}K"
                if r.coast_stuck_open_t_final_k is not None:
                    block += f" Tf_stuck={r.coast_stuck_open_t_final_k:.1f}K"
                    if r.louvers_stuck_below_lipo and r.coast_stuck_open_margin_lipo_k is not None:
                        block += (
                            f" BELOW LiPo limit margin={r.coast_stuck_open_margin_lipo_k:.1f}K"
                        )
            if r.dawn_warmup_energy_wh:
                block += f" warm={r.dawn_warmup_energy_wh/1000:.1f}kWh"
            ax.text(0.05, y, block, fontsize=7, family="monospace", va="top")
            y -= 0.055
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

        if n_pack_rows:
            sweep_lines = format_n_packs_table(n_pack_rows, cfg).splitlines()
            sweep_fs = 7.5
            dy = 0.0135
            fig, ax = plt.subplots(figsize=(8.5, 11))
            ax.axis("off")
            ax.set_position([0, 0, 1, 1])
            y = 0.98
            for line in sweep_lines:
                if y < 0.02:
                    pdf.savefig(fig)
                    plt.close(fig)
                    fig, ax = plt.subplots(figsize=(8.5, 11))
                    ax.axis("off")
                    ax.set_position([0, 0, 1, 1])
                    y = 0.98
                fig.text(
                    0.06,
                    y,
                    line,
                    fontsize=sweep_fs,
                    family="monospace",
                    va="top",
                    transform=fig.transFigure,
                )
                y -= dy
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
    coupling_set = rtg_module_enabled(cfg) and param_value(cfg, "rtg", "coupling_fraction") is not None

    placeholders = placeholder_list(cfg)
    print(format_results_table(results, coupling_set, cfg))
    n_sens = run_n_packs_sensitivity(cfg, specific_energy=param_value(cfg, "battery", "specific_energy_wh_per_kg_high") or 200)
    print(format_n_packs_table(n_sens, cfg))
    if placeholders:
        print("\n--- placeholder (example values, not Luke's design) ---")
        for t in placeholders:
            print(f"  • {t}")
    print("\n--- TODO-luke (complete list) ---")
    for t in todos:
        print(f"  • {t}")

    pdf_path = args.pdf or Path(param_value(cfg, "output", "report_pdf") or "report.pdf")
    write_report_pdf(pdf_path, cfg, results, sensitivity, todos, n_pack_rows=n_sens)
    print(f"\nWrote {pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())