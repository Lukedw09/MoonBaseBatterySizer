#!/usr/bin/env python3
"""Streamlit UI for Moon Base pack + radiator sizer (EXAMPLE config by default)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Optional, Tuple

import streamlit as st

from sizer import (
    DesignInputError,
    design_blockers,
    format_n_packs_table,
    format_results_table,
    load_config,
    param_value,
    run_all_cases,
    run_n_packs_sensitivity,
    rtg_module_enabled,
    validate_for_run,
    write_report_pdf,
)

EXAMPLE = Path(__file__).resolve().parent / "examples" / "example_config.yaml"

SIDEBAR_FIELDS: Tuple[Tuple[str, ...], str] = (
    (("geometry", "n_packs"), "n_packs"),
    (("loads", "primary_w"), "Night load (W)"),
    (("night", "t_dark_h"), "Night hours"),
    (("battery", "specific_energy_wh_per_kg_low"), "Specific energy low (Wh/kg)"),
    (("battery", "specific_energy_wh_per_kg_high"), "Specific energy high (Wh/kg)"),
    (("battery", "pack_volumetric_energy_density_wh_per_m3"), "Pack volumetric density (Wh/m³)"),
    (("battery", "depth_of_discharge"), "Depth of discharge"),
    (("battery", "efficiency"), "Discharge η"),
    (("battery", "packaging_insulation_mass_factor"), "Packaging factor"),
    (("battery", "box_target_temperature_k"), "T_box (K)"),
    (("radiator", "radiator_temperature_k"), "T_rad (K)"),
    (("radiator", "radiator_emissivity"), "Radiator ε"),
    (("wake_up", "warm_up_h"), "Warm-up h"),
    (("wake_up", "panel_efficiency"), "Panel η"),
    (("wake_up", "sun_incidence_cosine"), "cos(incidence)"),
)


def leaf_owner(cfg: dict, *keys: str) -> str:
    node = cfg
    for k in keys:
        node = node[k]
    if isinstance(node, dict):
        return str(node.get("owner") or "")
    return ""


def apply_if_changed(base_cfg: dict, cfg: dict, *keys: str, new_value: Any) -> None:
    base_val = param_value(base_cfg, *keys)
    path = cfg
    for k in keys[:-1]:
        path = path[k]
    leaf = path[keys[-1]]
    if not isinstance(leaf, dict):
        path[keys[-1]] = new_value
        return
    if base_val is not None and new_value == base_val:
        return
    prior = leaf.get("owner") or "unknown"
    leaf["value"] = new_value
    leaf["owner"] = f"ui-override (was {prior})" if prior != "ui-override" else "ui-override"


def owner_caption(base_cfg: dict, *keys: str) -> None:
    st.sidebar.caption(f"owner: {leaf_owner(base_cfg, *keys)}")


def require_param(cfg: dict, *keys: str, label: str):
    v = param_value(cfg, *keys)
    if v is None:
        st.sidebar.error(f"Missing required input: {label} ({'.'.join(keys)}) — use a complete config")
        st.stop()
    return v


def main() -> None:
    st.set_page_config(page_title="Moon Base Battery Sizer", layout="wide")
    st.title("Moon Base distributed pack sizer")
    st.caption("Loads a YAML config, validates design fields, then optional sliders (owner ui-override).")

    cfg_path = st.sidebar.text_input("Config YAML path", str(EXAMPLE))
    try:
        base_cfg = load_config(Path(cfg_path))
    except Exception as e:
        st.error(f"Could not load config: {e}")
        return

    blockers = design_blockers(base_cfg)
    if blockers:
        st.warning("Design incomplete — fix these before sliders or run:")
        for b in blockers:
            st.markdown(f"- `{b}`")
        st.info("Use `examples/example_config.yaml` for a complete EXAMPLE ONLY config.")
        return

    try:
        validate_for_run(base_cfg)
    except DesignInputError as e:
        st.warning("Additional blockers:")
        for m in e.missing:
            st.markdown(f"- `{m}`")
        return

    st.sidebar.header("Tuning (ui-override only when changed)")
    cfg = copy.deepcopy(base_cfg)
    n_packs = int(require_param(base_cfg, "geometry", "n_packs", label="n_packs"))
    rho = float(require_param(base_cfg, "battery", "pack_volumetric_energy_density_wh_per_m3", label="Wh/m³ density"))
    packaging = float(require_param(base_cfg, "battery", "packaging_insulation_mass_factor", label="packaging factor"))
    t_box = float(require_param(base_cfg, "battery", "box_target_temperature_k", label="T_box"))
    t_rad = float(require_param(base_cfg, "radiator", "radiator_temperature_k", label="T_rad"))
    e_rad = float(require_param(base_cfg, "radiator", "radiator_emissivity", label="radiator ε"))
    panel_eta = float(require_param(base_cfg, "wake_up", "panel_efficiency", label="panel η"))
    cos_i = float(require_param(base_cfg, "wake_up", "sun_incidence_cosine", label="cos incidence"))
    se_low = float(require_param(base_cfg, "battery", "specific_energy_wh_per_kg_low", label="Wh/kg low"))
    se_high = float(require_param(base_cfg, "battery", "specific_energy_wh_per_kg_high", label="Wh/kg high"))

    owner_caption(base_cfg, "geometry", "n_packs")
    n_packs = st.sidebar.slider("n_packs", 1, 16, n_packs)
    owner_caption(base_cfg, "loads", "primary_w")
    primary_w = st.sidebar.number_input("Night load (W)", 0.0, 20000.0, float(param_value(cfg, "loads", "primary_w")))
    owner_caption(base_cfg, "night", "t_dark_h")
    t_dark = st.sidebar.number_input("Night hours", 1.0, 240.0, float(param_value(cfg, "night", "t_dark_h")))
    owner_caption(base_cfg, "battery", "specific_energy_wh_per_kg_low")
    se_low = st.sidebar.number_input("Specific energy low (Wh/kg)", 50.0, 400.0, se_low)
    owner_caption(base_cfg, "battery", "specific_energy_wh_per_kg_high")
    se_high = st.sidebar.number_input("Specific energy high (Wh/kg)", 50.0, 400.0, se_high)
    owner_caption(base_cfg, "battery", "pack_volumetric_energy_density_wh_per_m3")
    rho = st.sidebar.number_input("Pack volumetric density (Wh/m³)", 50000.0, 500000.0, rho)
    owner_caption(base_cfg, "battery", "depth_of_discharge")
    dod = st.sidebar.slider("Depth of discharge", 0.1, 1.0, float(param_value(cfg, "battery", "depth_of_discharge")))
    owner_caption(base_cfg, "battery", "efficiency")
    eta = st.sidebar.slider("Discharge η", 0.5, 1.0, float(param_value(cfg, "battery", "efficiency")))
    owner_caption(base_cfg, "battery", "packaging_insulation_mass_factor")
    packaging = st.sidebar.number_input("Packaging factor", 0.5, 3.0, packaging)
    owner_caption(base_cfg, "battery", "box_target_temperature_k")
    t_box = st.sidebar.number_input("T_box (K)", 200.0, 310.0, t_box)
    owner_caption(base_cfg, "radiator", "radiator_temperature_k")
    t_rad = st.sidebar.number_input("T_rad (K)", 200.0, t_box, min(t_rad, t_box))
    owner_caption(base_cfg, "radiator", "radiator_emissivity")
    e_rad = st.sidebar.number_input("Radiator ε", 0.05, 1.0, e_rad)
    owner_caption(base_cfg, "wake_up", "warm_up_h")
    warm_h = st.sidebar.number_input("Warm-up h", 0.5, 24.0, float(param_value(cfg, "wake_up", "warm_up_h")))
    owner_caption(base_cfg, "wake_up", "panel_efficiency")
    panel_eta = st.sidebar.slider("Panel η", 0.05, 0.45, panel_eta)
    owner_caption(base_cfg, "wake_up", "sun_incidence_cosine")
    cos_i = st.sidebar.slider("cos(incidence)", 0.05, 1.0, cos_i)

    values = {
        ("geometry", "n_packs"): n_packs,
        ("loads", "primary_w"): primary_w,
        ("night", "t_dark_h"): t_dark,
        ("battery", "specific_energy_wh_per_kg_low"): se_low,
        ("battery", "specific_energy_wh_per_kg_high"): se_high,
        ("battery", "pack_volumetric_energy_density_wh_per_m3"): rho,
        ("battery", "depth_of_discharge"): dod,
        ("battery", "efficiency"): eta,
        ("battery", "packaging_insulation_mass_factor"): packaging,
        ("battery", "box_target_temperature_k"): t_box,
        ("radiator", "radiator_temperature_k"): t_rad,
        ("radiator", "radiator_emissivity"): e_rad,
        ("wake_up", "warm_up_h"): warm_h,
        ("wake_up", "panel_efficiency"): panel_eta,
        ("wake_up", "sun_incidence_cosine"): cos_i,
    }
    for keys, val in values.items():
        apply_if_changed(base_cfg, cfg, *keys, new_value=val)

    if st.sidebar.button("Run sizing"):
        validate_for_run(cfg)
        results = run_all_cases(cfg)
        coupling = rtg_module_enabled(cfg) and param_value(cfg, "rtg", "coupling_fraction") is not None
        st.text(format_results_table(results, coupling, cfg))
        sens = run_n_packs_sensitivity(cfg, specific_energy=se_high, n_list=(1, 2, 4, 8, 16))
        st.text(format_n_packs_table(sens))
        pdf_path = Path("streamlit_report.pdf")
        write_report_pdf(pdf_path, cfg, results, [], [], n_pack_rows=sens)
        with pdf_path.open("rb") as f:
            st.download_button("Download PDF report", f, file_name="moon_base_sizer_report.pdf")


if __name__ == "__main__":
    main()