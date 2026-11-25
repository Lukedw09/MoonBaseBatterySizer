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
    distributed_pack_radiation_loss_w,
    effective_sink_temperature_k,
    radiator_area_for_reject_w,
    total_pack_box_area_m2,
    run_n_packs_sensitivity,
    box_dims_from_volume,
    pack_volume_m3_per_pack,
    radiator_bare_and_deployed_area_m2,
    scaled_pack_dims_for_n_packs,
    solve_dawn_warmup_solar_w,
    electric_heater_alternative,
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
    build_q_loss_temperature_lut,
    integrate_lumped_thermal_coast,
    solve_case,
    solve_cold_shutdown_case,
    solve_dawn_warmup_heater_w,
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


def test_missing_list_includes_n_packs():
    cfg = load_config(LUKE_CFG)
    missing = blocking_missing(cfg)
    assert "geometry.n_packs" in missing


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


def test_zero_packs_raises(example_cfg):
    bad = yaml.safe_load(yaml.dump(example_cfg))
    bad["geometry"]["n_packs"]["value"] = 0
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


def test_per_pack_face_area_literal():
    assert total_pack_box_area_m2(1.0, 0.8, 0.6) == pytest.approx(3.76, rel=1e-4)


def test_fleet_box_area_scales_n_one_third():
    rho = 250_000.0
    cap = 500_000.0
    vol1 = cap / rho
    l1, w1, h1 = box_dims_from_volume(1.0, 0.8, 0.6, vol1)
    a1 = total_pack_box_area_m2(l1, w1, h1)
    for n in (2, 4, 8):
        vol_n = (cap / n) / rho
        ln, wn, hn = box_dims_from_volume(1.0, 0.8, 0.6, vol_n)
        a_n = n * total_pack_box_area_m2(ln, wn, hn)
        assert a_n == pytest.approx(a1 * (n ** (1 / 3)), rel=0.001)


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


def test_per_pack_box_radiation_hand_calc(example_cfg):
    n_p = 8
    rho = param_value(example_cfg, "battery", "pack_volumetric_energy_density_wh_per_m3")
    cap = compute_required_capacity_wh((5000 + 0) * 72, 0.8, 0.9)
    vol = pack_volume_m3_per_pack(cap, n_p, rho)
    l, w, h = box_dims_from_volume(
        param_value(example_cfg, "geometry", "box_length_m"),
        param_value(example_cfg, "geometry", "box_width_m"),
        param_value(example_cfg, "geometry", "box_height_m"),
        vol,
    )
    em = param_value(example_cfg, "radiation", "box_effective_emittance")
    mult = param_value(example_cfg, "radiation", "penetration_seam_emittance_multiplier") or 1.0
    t_box = param_value(example_cfg, "battery", "box_target_temperature_k")
    t_sky = param_value(example_cfg, "thermal_environment", "deep_space_sink_k")
    t_g = param_value(example_cfg, "thermal_environment", "night_surface_k")
    fs = param_value(example_cfg, "geometry", "view_factor_sky_vertical")
    fg = param_value(example_cfg, "geometry", "view_factor_ground_vertical")
    q1, _, _ = distributed_pack_radiation_loss_w(l, w, h, em, t_box, t_sky, t_g, fs, fg, mult, SIGMA_DEFAULT)
    expected_fleet = 122.91357399596148
    assert q1 * n_p == pytest.approx(expected_fleet, rel=0.001)


def test_radiator_area_hand_calc():
    q_pp = 33.71944289488082
    eps = 0.92
    t_rad = 273.15
    t_sink = effective_sink_temperature_k(3.0, 40.0)
    bare, deployed = radiator_bare_and_deployed_area_m2(q_pp, eps, t_rad, t_sink, 1.3, SIGMA_DEFAULT)
    assert bare == pytest.approx(0.11613841146546709, rel=0.001)
    assert deployed == pytest.approx(0.15097993490510722, rel=0.001)


def test_example_primary_thermal_targets(example_cfg):
    r = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    assert r.q_internal_w == pytest.approx(555.56, rel=0.001)
    assert r.thermal.q_leg_w > 0
    th = r.thermal
    assert th.q_total_w == pytest.approx(
        th.q_box_rad_w + th.q_leg_w + th.q_passthrough_w + th.q_radiator_night_leak_w, rel=1e-4
    )


def test_example_known_primary_thermal_numbers(example_cfg):
    r = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    assert r.thermal.q_leg_w == pytest.approx(162.89855761554043, rel=0.001)
    assert r.thermal.q_total_w == pytest.approx(285.8000123965092, rel=0.001)
    assert r.q_internal_w == pytest.approx(555.5555555555555, rel=0.001)
    assert r.q_excess_w == pytest.approx(269.75554315904657, rel=0.001)
    assert r.thermal.radiator_area_per_pack_m2 == pytest.approx(0.15097993490510722, rel=0.001)
    assert r.battery.capacity_wh == pytest.approx(500_000.0, rel=0.001)


def test_example_same_pack_survival_transient_dt(example_cfg):
    prim = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    surv = solve_case(
        "survival_100W", 100, 200, example_cfg,
        fallback_branch="same_pack_survival", primary_pack=prim.battery, transient_mass_kg=prim.battery.mass_kg,
    )
    assert surv.transient_delta_t_k == pytest.approx(-28.479745285270077, rel=0.001)


def test_lander_deck_missing_temperature_raises_ring_layout(example_cfg):
    bad = copy.deepcopy(example_cfg)
    bad["layout"]["model"]["value"] = "ring_rtg"
    bad.setdefault("geometry", {})["n_battery_boxes"] = {"value": 8, "owner": "placeholder"}
    bad["geometry"]["ring_radius_m"] = {"value": 3.0, "owner": "placeholder"}
    bad["geometry"]["bottom_radiates_to"] = {"value": "lander_deck", "owner": "placeholder"}
    bad["thermal_environment"]["lander_deck_temperature_k"]["value"] = None
    with pytest.raises(ConfigError, match="lander_deck_temperature_k"):
        compute_thermal_loss(bad, fleet_capacity_wh=500_000.0)


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
    cfg["rtg"]["enabled"] = {"value": True, "owner": "placeholder"}
    cfg["rtg"]["coupling_fraction"]["value"] = 0.034
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


def test_n_packs_sensitivity_row_eight(example_cfg):
    rows = run_n_packs_sensitivity(example_cfg, specific_energy=200, n_list=(8,))
    assert rows[0]["q_loss_w"] == pytest.approx(285.8000123965092, rel=0.001)
    assert rows[0]["cold_tf_k"] == pytest.approx(245.0200397810733, rel=0.001)


def test_fallback_both_branches_when_unset(example_cfg):
    cfg = copy.deepcopy(example_cfg)
    cfg["fallback"]["mode"]["value"] = None
    results = run_all_cases(cfg)
    branches = {r.fallback_branch for r in results if "survival" in r.load_name}
    assert branches == {"same_pack_survival", "separate_pack"}


def test_solve_case_end_to_end(example_cfg):
    r = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    coupling = param_value(example_cfg, "rtg", "coupling_fraction")
    assert r.battery.mass_kg > 1000
    assert r.thermal.q_total_w > 100
    assert r.q_rtg_total_w is None
    assert r.q_excess_w == pytest.approx(269.75554315904657, rel=0.001)
    assert r.system_mass_kg is not None and r.system_mass_kg > r.battery.mass_kg


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


def test_cold_shutdown_final_t_on_example(example_cfg):
    prim = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    n_p = max(1, prim.thermal.n_packs)
    mass_pp = prim.battery.mass_kg / n_p
    cp = param_value(example_cfg, "battery", "pack_specific_heat_j_per_kgk")
    t_dark = param_value(example_cfg, "night", "t_dark_h")
    q_ex_pp = prim.q_excess_w / n_p
    q_const = 39.537641346624724
    t0 = param_value(example_cfg, "battery", "box_target_temperature_k")
    t_analytic = t0 - q_const * t_dark * 3600.0 / (mass_pp * cp)
    cs = solve_cold_shutdown_case(example_cfg, prim, dt_s=60.0)
    assert cs.coast_t_final_k == pytest.approx(245.0200397810733, rel=0.001)
    assert t_analytic == pytest.approx(240.35039839406228, rel=0.001)
    assert cs.coast_t_final_k >= t_analytic
    assert cs.coast_margin_lipo_k == pytest.approx(cs.coast_t_final_k - 233.0, rel=0.01)
    assert cs.coast_time_to_lipo_h is None


def test_dawn_warmup_energy_hand_calc(example_cfg):
    mass = 2500.0
    cp = 1000.0
    t0, t_target = 254.2, 273.15
    tau_h = 6.0
    q0 = 100.0
    lut = ([200.0, 280.0], [q0, q0])
    mc = mass * cp
    d_t = t_target - t0
    p_hand = mc * d_t / (tau_h * 3600.0) + q0
    w = solve_dawn_warmup_solar_w(
        example_cfg, mass, cp, t0, t_target, tau_h, dt_s=60.0, q_loss_lut=lut,
        fleet_capacity_wh=500_000.0, q_excess_per_pack_w=0.0,
    )
    assert w["p_heater_w"] == pytest.approx(p_hand, rel=0.001)
    assert w["energy_wh"] == pytest.approx(p_hand * tau_h, rel=0.001)


def test_electric_heater_alt_hand_calc(example_cfg):
    prim = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    surv = solve_case(
        "survival_100W", 100, 200, example_cfg,
        fallback_branch="same_pack_survival", primary_pack=prim.battery,
    )
    eta = 0.9
    q_int, _ = pick_internal_heat(internal_waste_heat_w(100, eta), "discharge")
    p_exp = eta * (surv.thermal.q_total_w - q_int)
    alt = electric_heater_alternative(surv)
    assert alt["p_shortfall_w"] == pytest.approx(p_exp, rel=0.001)
    assert alt["e_heater_wh"] == pytest.approx(p_exp * 72, rel=0.001)