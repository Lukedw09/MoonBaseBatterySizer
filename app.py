#!/usr/bin/env python3
"""Streamlit UI for Moon Base pack + radiator sizer (EXAMPLE config by default)."""

from __future__ import annotations

import copy
from pathlib import Path

import streamlit as st
import yaml

from sizer import (
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


def set_param_value(cfg: dict, *keys: str, value) -> None:
    node = cfg
    for k in keys[:-1]:
        node = node[k]
    leaf = node[keys[-1]]
    if isinstance(leaf, dict) and "value" in leaf:
        leaf["value"] = value
    else:
        node[keys[-1]] = value


def main() -> None:
    st.set_page_config(page_title="Moon Base Battery Sizer", layout="wide")
    st.title("Moon Base distributed pack sizer")
    st.caption("EXAMPLE ONLY unless you load Luke's config.yaml with all TODO-luke fields set.")

    cfg_path = st.sidebar.text_input("Config YAML path", str(EXAMPLE))
    try:
        cfg = load_config(Path(cfg_path))
    except Exception as e:
        st.error(f"Could not load config: {e}")
        return

    st.sidebar.header("Tuning sliders")
    n_packs = st.sidebar.slider("n_packs", 1, 16, int(param_value(cfg, "geometry", "n_packs") or 8))
    primary_w = st.sidebar.number_input("Night load (W)", 0.0, 20000.0, float(param_value(cfg, "loads", "primary_w")))
    t_dark = st.sidebar.number_input("Night hours", 1.0, 240.0, float(param_value(cfg, "night", "t_dark_h")))
    se = st.sidebar.number_input("Specific energy (Wh/kg)", 50.0, 400.0, float(param_value(cfg, "battery", "specific_energy_wh_per_kg_high")))
    rho = st.sidebar.number_input(
        "Pack volumetric density (Wh/m³)", 50000.0, 500000.0,
        float(param_value(cfg, "battery", "pack_volumetric_energy_density_wh_per_m3") or 250000),
    )
    dod = st.sidebar.slider("Depth of discharge", 0.1, 1.0, float(param_value(cfg, "battery", "depth_of_discharge")))
    eta = st.sidebar.slider("Discharge η", 0.5, 1.0, float(param_value(cfg, "battery", "efficiency")))
    packaging = st.sidebar.number_input(
        "Packaging factor", 0.5, 3.0, float(param_value(cfg, "battery", "packaging_insulation_mass_factor") or 1.0)
    )
    t_box = st.sidebar.number_input("T_box (K)", 200.0, 310.0, float(param_value(cfg, "battery", "box_target_temperature_k")))
    t_rad = st.sidebar.number_input("T_rad (K)", 200.0, t_box, float(param_value(cfg, "radiator", "radiator_temperature_k") or t_box))
    e_rad = st.sidebar.number_input(
        "Radiator ε", 0.05, 1.0, float(param_value(cfg, "radiator", "radiator_emissivity") or 0.92)
    )
    warm_h = st.sidebar.number_input("Warm-up h", 0.5, 24.0, float(param_value(cfg, "wake_up", "warm_up_h") or 6))
    panel_eta = st.sidebar.slider(
        "Panel η", 0.05, 0.45, float(param_value(cfg, "wake_up", "panel_efficiency") or 0.28)
    )
    cos_i = st.sidebar.slider(
        "cos(incidence)", 0.05, 1.0, float(param_value(cfg, "wake_up", "sun_incidence_cosine") or 0.35)
    )

    c = copy.deepcopy(cfg)
    set_param_value(c, "geometry", "n_packs", value=int(n_packs))
    set_param_value(c, "loads", "primary_w", value=float(primary_w))
    set_param_value(c, "night", "t_dark_h", value=float(t_dark))
    set_param_value(c, "battery", "specific_energy_wh_per_kg_low", value=float(se))
    set_param_value(c, "battery", "specific_energy_wh_per_kg_high", value=float(se))
    set_param_value(c, "battery", "pack_volumetric_energy_density_wh_per_m3", value=float(rho))
    set_param_value(c, "battery", "depth_of_discharge", value=float(dod))
    set_param_value(c, "battery", "efficiency", value=float(eta))
    set_param_value(c, "battery", "packaging_insulation_mass_factor", value=float(packaging))
    set_param_value(c, "battery", "box_target_temperature_k", value=float(t_box))
    set_param_value(c, "radiator", "radiator_temperature_k", value=float(t_rad))
    set_param_value(c, "radiator", "radiator_emissivity", value=float(e_rad))
    set_param_value(c, "wake_up", "warm_up_h", value=float(warm_h))
    set_param_value(c, "wake_up", "panel_efficiency", value=float(panel_eta))
    set_param_value(c, "wake_up", "sun_incidence_cosine", value=float(cos_i))

    if st.sidebar.button("Run sizing"):
        try:
            validate_for_run(c)
            results = run_all_cases(c)
            coupling = rtg_module_enabled(c) and param_value(c, "rtg", "coupling_fraction") is not None
            st.text(format_results_table(results, coupling, c))
            sens = run_n_packs_sensitivity(c, specific_energy=se, n_list=(1, 2, 4, 8, 16))
            st.text(format_n_packs_table(sens))
            pdf_path = Path("streamlit_report.pdf")
            write_report_pdf(pdf_path, c, results, [], [])
            with pdf_path.open("rb") as f:
                st.download_button("Download PDF report", f, file_name="moon_base_sizer_report.pdf")
        except Exception as e:
            st.exception(e)


if __name__ == "__main__":
    main()