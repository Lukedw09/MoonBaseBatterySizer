"""Hand-checked closed-form and end-to-end tests."""

from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest
import yaml

from sizer import (
    ConfigError,
    DesignInputError,
    FinSolverError,
    SIGMA_DEFAULT,
    analytic_constant_h_fin_w,
    blocking_missing,
    bvp_constant_h_fin_w,
    box_radiation_loss_w,
    compute_night_energy_wh,
    compute_pack_mass_kg,
    compute_required_capacity_wh,
    compute_series_count,
    compute_thermal_loss,
    discharge_efficiency_for_sizing,
    end_face_exposure_factor,
    heater_shortfall_w,
    internal_waste_heat_w,
    leg_conduction_network_w,
    load_config,
    net_rtg_need_w,
    param_value,
    per_box_face_areas_m2,
    pick_internal_heat,
    radiation_loss_w,
    regolith_spreading_resistance_k_per_w,
    run_all_cases,
    solve_case,
    solve_linear_h_fin_bvp,
    solve_radiating_leg_fin,
    total_ring_radiating_area_m2,
    validate_for_run,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "example_config.yaml"
LUKE_CFG = ROOT / "config.yaml"

FIN_BENCH = dict(k_leg=6.7, a_cross=0.001, perimeter_m=0.126, length_m=1.0, t_root=350.0, t_inf=40.0, h_lin=2.0)
LEG_BVP = dict(
    k_leg=6.7,
    a_cross=0.001,
    perimeter_m=0.126,
    length_m=1.0,
    leg_emissivity=0.9,
    t_root_k=273.15,
    t_sky_k=3.0,
    t_ground_k=40.0,
    t_surf_k=40.0,
    f_sky=0.5,
    f_ground=0.5,
    footpad_area=0.05,
    h_contact=10.0,
    k_regolith=7.4e-4,
    sigma=SIGMA_DEFAULT,
)


@pytest.fixture
def example_cfg():
    return load_config(EXAMPLE)


def test_night_energy_wh():
    p, ph, h = 5000, 0, 72
    assert compute_night_energy_wh(p, ph, h) == (p + ph) * h


def test_pack_mass_hand_calc():
    cap = 500_000.0
    assert compute_pack_mass_kg(cap, 200.0, 1.0) == pytest.approx(2500.0, rel=1e-4)


def test_capacity_uses_discharge_eta_round_trip():
    e = 360_000
    eta_dis = discharge_efficiency_for_sizing(0.9, "round_trip")
    assert compute_required_capacity_wh(e, 0.8, eta_dis) == pytest.approx(e / (0.8 * eta_dis))


def test_internal_heat_both_independent():
    q = internal_waste_heat_w(5000, 0.9)
    assert q["round_trip_definition"] == pytest.approx(5000 * (1 / 0.9**0.5 - 1), rel=1e-6)
    assert q["discharge_definition"] == pytest.approx(5000 * (1 / 0.9 - 1), rel=1e-6)
    assert q["discharge_definition"] != q["round_trip_definition"]


def test_pick_internal_matches_eta_definition_round_trip():
    q = internal_waste_heat_w(5000, 0.9)
    val, note = pick_internal_heat(q, "round_trip")
    assert note == "round_trip"
    assert val == q["round_trip_definition"]


def test_luke_config_still_blocks_until_geometry_set():
    cfg = load_config(LUKE_CFG)
    missing = blocking_missing(cfg)
    assert "battery.eta_definition" not in missing
    assert "fallback.mode" not in missing
    with pytest.raises(DesignInputError):
        validate_for_run(cfg)


def test_missing_list_includes_coupling():
    cfg = load_config(LUKE_CFG)
    missing = blocking_missing(cfg)
    assert "rtg.coupling_fraction" in missing


def test_net_rtg_with_coupling_unset():
    q_rtg, excess = net_rtg_need_w(211.0, 50.0, None)
    assert q_rtg is None
    assert excess == 0.0


def test_coupling_zero_raises():
    with pytest.raises(ConfigError):
        net_rtg_need_w(100.0, 0.0, 0.0)


def test_zero_legs_raises():
    bad = load_config(EXAMPLE)
    bad["lander_legs"]["n_legs"]["value"] = 0
    with pytest.raises(ConfigError):
        validate_for_run(bad)


def test_zero_boxes_raises(example_cfg):
    bad = yaml.safe_load(yaml.dump(example_cfg))
    bad["geometry"]["n_battery_boxes"]["value"] = 0
    with pytest.raises(ConfigError):
        validate_for_run(bad)


def test_series_count_hand_calc(example_cfg):
    bus = param_value(example_cfg, "battery", "bus_voltage_v")
    cell = param_value(example_cfg, "battery", "cell_nominal_voltage_v")
    assert compute_series_count(bus, cell) == math.ceil(bus / cell)


def test_per_box_faces_hand_calc():
    ef = end_face_exposure_factor(8, 3.0, 1.0, 0.8)
    faces = per_box_face_areas_m2(1.0, 0.8, 0.6, ef)
    assert faces["outer_vertical"] == 0.6
    assert faces["top"] == 0.8
    assert faces["ends"] == pytest.approx(2 * 0.8 * 0.6 * ef, rel=1e-9)


def test_radiation_zero_at_uniform_T():
    t = 273.15
    assert radiation_loss_w(0.02, 10.0, t, t, t, 0.5, 0.5) == 0.0


def test_ring_area_eight_boxes():
    total, _ = total_ring_radiating_area_m2(8, 1.0, 0.8, 0.6, 3.0)
    assert total == pytest.approx(30.08, rel=1e-4)


def test_regolith_spreading_disk_formula():
    a_pad = 0.05
    k = 7.4e-4
    r = regolith_spreading_resistance_k_per_w(a_pad, k)
    radius = math.sqrt(a_pad / math.pi)
    assert r == pytest.approx(1.0 / (4 * k * radius), rel=1e-6)


def test_leg_conduction_hand_calc():
    q = leg_conduction_network_w(
        n_legs=4, k_leg=6.7, a_cross=0.001, length_m=1.0, t_box_k=273.15, t_surface_k=40.0,
        footpad_area=0.05, h_contact=10.0, k_regolith=7.4e-4,
    )
    r_leg = 1.0 / (6.7 * 0.001)
    r_c = 1.0 / (10 * 0.05)
    a = math.sqrt(0.05 / math.pi)
    r_r = 1.0 / (4 * 7.4e-4 * a)
    expected = 4 * (273.15 - 40) / (r_leg + r_c + r_r)
    assert q == pytest.approx(expected, rel=1e-4)


def test_constant_h_fin_analytic_fd_tanh():
    qa = analytic_constant_h_fin_w(**FIN_BENCH)
    m = math.sqrt(FIN_BENCH["h_lin"] * FIN_BENCH["perimeter_m"] / (FIN_BENCH["k_leg"] * FIN_BENCH["a_cross"]))
    m_val = math.sqrt(
        FIN_BENCH["h_lin"] * FIN_BENCH["perimeter_m"] * FIN_BENCH["k_leg"] * FIN_BENCH["a_cross"]
    )
    manual = m_val * (FIN_BENCH["t_root"] - FIN_BENCH["t_inf"]) * math.tanh(m * FIN_BENCH["length_m"])
    assert qa == pytest.approx(manual, rel=1e-9)
    for n in (12, 50, 200):
        qn = bvp_constant_h_fin_w(**FIN_BENCH, n_nodes=n)
        assert qn == pytest.approx(qa, rel=0.002)


def test_linear_fin_bvp_forced_failure():
    with pytest.raises(FinSolverError):
        solve_linear_h_fin_bvp(
            FIN_BENCH["k_leg"],
            FIN_BENCH["a_cross"],
            FIN_BENCH["perimeter_m"],
            FIN_BENCH["length_m"],
            FIN_BENCH["t_root"],
            FIN_BENCH["t_inf"],
            FIN_BENCH["h_lin"],
            12,
            max_nodes=8,
        )


def test_radiating_leg_bvp_forced_failure():
    with pytest.raises(FinSolverError):
        solve_radiating_leg_fin(**LEG_BVP, n_nodes=12, max_nodes=8)


def test_radiating_leg_grid_convergence():
    q_ref, t_ref, _ = solve_radiating_leg_fin(**LEG_BVP, n_nodes=200)
    q_ref_4 = 4 * q_ref
    rows = []
    for n in (12, 50, 100, 200):
        q, tf, _ = solve_radiating_leg_fin(**LEG_BVP, n_nodes=n)
        q4 = 4 * q
        rows.append((n, q4, tf, abs(q4 - q_ref_4) / q_ref_4))
        assert q4 == pytest.approx(q_ref_4, rel=0.01)
        assert tf == pytest.approx(t_ref, rel=0.01)


def test_radiating_leg_example_vs_reference(example_cfg):
    n_seg = param_value(example_cfg, "lander_legs", "leg_fin_segments")
    q_ref, _, _ = solve_radiating_leg_fin(**LEG_BVP, n_nodes=200)
    q_n, t_foot, _ = solve_radiating_leg_fin(**LEG_BVP, n_nodes=n_seg)
    n_legs = param_value(example_cfg, "lander_legs", "n_legs")
    assert n_legs * q_n == pytest.approx(n_legs * q_ref, rel=0.01)
    assert t_foot == pytest.approx(110.7, abs=0.5)


def test_box_radiation_hand_calc(example_cfg):
    n = param_value(example_cfg, "geometry", "n_battery_boxes")
    l = param_value(example_cfg, "geometry", "box_length_m")
    w = param_value(example_cfg, "geometry", "box_width_m")
    h = param_value(example_cfg, "geometry", "box_height_m")
    r = param_value(example_cfg, "geometry", "ring_radius_m")
    em = param_value(example_cfg, "radiation", "box_effective_emittance")
    mult = param_value(example_cfg, "radiation", "penetration_seam_emittance_multiplier") or 1.0
    t_box = param_value(example_cfg, "battery", "box_target_temperature_k")
    t_sky = param_value(example_cfg, "thermal_environment", "deep_space_sink_k")
    t_g = param_value(example_cfg, "thermal_environment", "night_surface_k")
    fs = param_value(example_cfg, "geometry", "view_factor_sky_vertical")
    fg = param_value(example_cfg, "geometry", "view_factor_ground_vertical")
    bottom = param_value(example_cfg, "geometry", "bottom_radiates_to")
    q, _, _ = box_radiation_loss_w(
        n, l, w, h, r, em, t_box, t_sky, t_g, t_g, bottom, fs, fg, mult, SIGMA_DEFAULT,
    )
    assert q == pytest.approx(189.86, rel=0.01)


def test_example_primary_thermal_targets(example_cfg):
    r = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    assert r.q_internal_w == pytest.approx(555.56, rel=0.001)
    assert r.thermal.q_leg_w > 0
    assert r.thermal.q_total_w == pytest.approx(r.thermal.q_box_rad_w + r.thermal.q_leg_w + r.thermal.q_passthrough_w, rel=1e-4)


def test_example_known_primary_thermal_numbers(example_cfg):
    r = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    assert r.thermal.q_leg_w == pytest.approx(20.36, rel=0.001)
    assert r.thermal.q_total_w == pytest.approx(210.22, rel=0.001)
    assert r.q_internal_w == pytest.approx(555.56, rel=0.001)
    assert r.q_excess_w == pytest.approx(345.34, rel=0.001)
    assert r.battery.capacity_wh == pytest.approx(500_000.0, rel=0.001)


def test_example_same_pack_survival_transient_dt(example_cfg):
    prim = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    surv = solve_case(
        "survival_100W", 100, 200, example_cfg,
        fallback_branch="same_pack_survival", primary_pack=prim.battery, transient_mass_kg=prim.battery.mass_kg,
    )
    assert surv.transient_delta_t_k == pytest.approx(-20.64, rel=0.001)


def test_lander_deck_missing_temperature_raises(example_cfg):
    bad = copy.deepcopy(example_cfg)
    bad["geometry"]["bottom_radiates_to"]["value"] = "lander_deck"
    bad["thermal_environment"]["lander_deck_temperature_k"]["value"] = None
    with pytest.raises(ConfigError, match="lander_deck_temperature_k"):
        compute_thermal_loss(bad)


def test_primary_more_internal_than_survival(example_cfg):
    rp = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    rs = solve_case("survival_100W", 100, 200, example_cfg, fallback_branch="primary")
    assert rp.q_internal_w > rs.q_internal_w


def test_same_pack_reuses_primary_mass(example_cfg):
    prim = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    surv = solve_case(
        "survival_100W", 100, 200, example_cfg,
        fallback_branch="same_pack_survival", primary_pack=prim.battery, transient_mass_kg=prim.battery.mass_kg,
    )
    assert surv.battery.mass_kg == pytest.approx(prim.battery.mass_kg)
    assert surv.battery.capacity_wh == pytest.approx(prim.battery.capacity_wh)


def test_same_pack_without_primary_raises(example_cfg):
    with pytest.raises(ConfigError, match="primary_pack"):
        solve_case("survival_100W", 100, 200, example_cfg, fallback_branch="same_pack_survival")


def test_fixed_rtg_heater_iteration(example_cfg):
    cfg = copy.deepcopy(example_cfg)
    cfg["meta"]["mode"] = "fixed_rtg"
    cfg["rtg"]["thermal_output_w"]["value"] = 10.0
    prim = solve_case("primary_5000W", 5000, 200, cfg, fallback_branch="primary")
    r = solve_case(
        "survival_100W", 100, 200, cfg,
        fallback_branch="same_pack_survival", primary_pack=prim.battery, transient_mass_kg=prim.battery.mass_kg,
    )
    coupling = param_value(cfg, "rtg", "coupling_fraction")
    q_int, _ = pick_internal_heat(internal_waste_heat_w(100, param_value(cfg, "battery", "efficiency")), "discharge")
    q_rtg_del = coupling * 10.0
    expected_h = heater_shortfall_w(r.thermal.q_total_w, q_int, coupling, 10.0)
    assert r.battery.p_heater_w == pytest.approx(expected_h, rel=1e-4)
    assert r.battery.p_heater_w == pytest.approx(r.thermal.q_total_w - q_int - q_rtg_del, rel=1e-3)


def test_fixed_rtg_requires_thermal_output(example_cfg):
    bad = copy.deepcopy(example_cfg)
    bad["meta"]["mode"] = "fixed_rtg"
    bad["rtg"]["thermal_output_w"]["value"] = None
    with pytest.raises(ConfigError):
        validate_for_run(bad)


def test_fallback_both_branches_when_unset(example_cfg):
    cfg = copy.deepcopy(example_cfg)
    cfg["fallback"]["mode"]["value"] = None
    results = run_all_cases(cfg)
    branches = {r.fallback_branch for r in results if "survival" in r.load_name}
    assert branches == {"same_pack_survival", "separate_pack"}


def test_solve_case_end_to_end(example_cfg):
    r = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    coupling = param_value(example_cfg, "rtg", "coupling_fraction")
    q_rtg_exp, excess_exp = net_rtg_need_w(r.thermal.q_total_w, r.q_internal_w, coupling)
    assert r.battery.mass_kg > 1000
    assert r.thermal.q_total_w > 100
    assert r.q_rtg_total_w == pytest.approx(q_rtg_exp, rel=1e-6)
    assert r.q_excess_w == pytest.approx(excess_exp, rel=1e-6)
    assert r.q_excess_w > 0


def test_net_rtg_clamps_and_excess():
    q_rtg, excess = net_rtg_need_w(100, 150, 0.5)
    assert q_rtg == 0.0
    assert excess == 50.0


def test_heater_shortfall_includes_internal():
    assert heater_shortfall_w(1000, 200, 1.0, 500) == 300


def test_end_face_reduction_when_gap_small():
    f = end_face_exposure_factor(8, 1.0, 1.0, 0.8)
    assert f == 0.0


def test_battery_efficiency_missing_raises():
    cfg = load_config(EXAMPLE)
    del cfg["battery"]["efficiency"]
    with pytest.raises(ConfigError, match="efficiency"):
        solve_case("primary_5000W", 5000, 200, cfg, fallback_branch="primary")