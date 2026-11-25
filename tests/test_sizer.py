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
    radiator_night_leak_w,
    effective_sink_temperature_k,
    solve_dawn_warmup_solar_w,
    design_blockers,
    thermal_q_loss_at_box_t,
    break_even_load_w,
    discharge_efficiency_for_sizing,
    battery_efficiency_value,
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
    solve_linear_h_fin_bvp,
    solve_radiating_leg_fin,
    total_ring_radiating_area_m2,
    validate_for_run,
    write_report_pdf,
    todo_luke_list,
    figure_text_extents_pdf_scaled,
    format_n_packs_table,
    SWEEP_PDF_PAGE_LABEL,
    SWEEP_PDF_GLYPH_WIDTH_SCALE,
    sweep_pdf_glyph_width_scale,
    N_PACK_SWEEP_FONT_SIZE,
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


def _box_surface_m2(l: float, w: float, h: float) -> float:
    return 2.0 * (l * h + w * h) + 2.0 * (l * w)


def test_fleet_box_area_scales_n_one_third():
    rho, cap, v_ref = 250_000.0, 500_000.0, 1.0 * 0.8 * 0.6
    vol1 = cap / rho
    s1 = (vol1 / v_ref) ** (1.0 / 3.0)
    a1 = _box_surface_m2(1.0 * s1, 0.8 * s1, 0.6 * s1)
    for n in (2, 4, 8):
        vol_n = (cap / n) / rho
        sn = (vol_n / v_ref) ** (1.0 / 3.0)
        a_n = n * _box_surface_m2(1.0 * sn, 0.8 * sn, 0.6 * sn)
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
    r = solve_case("primary_5000W", 5000, 200, example_cfg, case_branch="primary")
    assert r.q_internal_w == pytest.approx(555.56, rel=0.001)
    assert r.thermal.q_leg_w > 0
    th = r.thermal
    assert th.q_total_w == pytest.approx(
        th.q_box_rad_w + th.q_leg_w + th.q_passthrough_w + th.q_radiator_night_leak_w, rel=1e-4
    )


def test_example_known_primary_thermal_numbers(example_cfg):
    r = solve_case("primary_5000W", 5000, 200, example_cfg, case_branch="primary")
    assert r.thermal.q_leg_w == pytest.approx(162.89855761554043, rel=0.001)
    assert r.thermal.q_total_w == pytest.approx(285.8000123965092, rel=0.001)
    assert r.q_internal_w == pytest.approx(555.5555555555555, rel=0.001)
    assert r.q_excess_w == pytest.approx(269.75554315904657, rel=0.001)
    assert r.thermal.radiator_area_per_pack_m2 == pytest.approx(0.15097993490510722, rel=0.001)
    assert r.battery.capacity_wh == pytest.approx(500_000.0, rel=0.001)


def test_lander_deck_missing_temperature_raises_ring_layout(example_cfg):
    bad = copy.deepcopy(example_cfg)
    bad["layout"]["model"]["value"] = "ring_rtg"
    bad.setdefault("geometry", {})["n_battery_boxes"] = {"value": 8, "owner": "placeholder"}
    bad["geometry"]["ring_radius_m"] = {"value": 3.0, "owner": "placeholder"}
    bad["geometry"]["bottom_radiates_to"] = {"value": "lander_deck", "owner": "placeholder"}
    bad["thermal_environment"]["lander_deck_temperature_k"]["value"] = None
    with pytest.raises(ConfigError, match="lander_deck_temperature_k"):
        compute_thermal_loss(bad, fleet_capacity_wh=500_000.0)


def test_fixed_rtg_heater_iteration(example_cfg):
    cfg = copy.deepcopy(example_cfg)
    cfg["meta"]["mode"] = "fixed_rtg"
    cfg["rtg"]["enabled"] = {"value": True, "owner": "placeholder"}
    cfg["rtg"]["coupling_fraction"]["value"] = 0.034
    cfg["rtg"]["thermal_output_w"]["value"] = 10.0
    prim = solve_case("primary_5000W", 5000, 200, cfg, case_branch="primary")
    r = solve_case("low_load_100W", 100, 200, cfg, case_branch="primary")
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
    assert rows[0]["q_loss_fleet_w"] == pytest.approx(285.8000123965092, rel=0.001)
    assert rows[0]["cold_tf_k"] == pytest.approx(245.57321183820113, rel=0.001)
    assert rows[0]["cold_tf_stuck_k"] == pytest.approx(230.70323875995143, rel=0.001)
    assert rows[0]["p_be_w"] == pytest.approx(2846.6470554782204, rel=0.001)


def test_run_all_cases_primary_and_cold_only(example_cfg):
    results = run_all_cases(example_cfg)
    assert len(results) == 4
    names = {r.load_name for r in results}
    assert names == {"primary_5000W", "cold_shutdown_0W"}


def test_solve_case_end_to_end(example_cfg):
    r = solve_case("primary_5000W", 5000, 200, example_cfg, case_branch="primary")
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
        solve_case("primary_5000W", 5000, 200, cfg, case_branch="primary")


def test_cold_shutdown_final_t_on_example(example_cfg):
    prim = solve_case("primary_5000W", 5000, 200, example_cfg, case_branch="primary")
    n_p = max(1, prim.thermal.n_packs)
    mass_pp = prim.battery.mass_kg / n_p
    cp = param_value(example_cfg, "battery", "pack_specific_heat_j_per_kgk")
    t_dark = param_value(example_cfg, "night", "t_dark_h")
    q_ex_pp = prim.q_excess_w / n_p
    t0 = param_value(example_cfg, "battery", "box_target_temperature_k")
    q_pp_hold = thermal_q_loss_at_box_t(
        example_cfg, t0, fleet_capacity_wh=500_000.0, q_excess_per_pack_w=q_ex_pp
    )
    t_const_loss = t0 - q_pp_hold * t_dark * 3600.0 / (mass_pp * cp)
    cs = solve_cold_shutdown_case(example_cfg, prim, dt_s=60.0)
    assert mass_pp == pytest.approx(312.5, rel=1e-6)
    assert q_pp_hold == pytest.approx(39.536764659419745, rel=0.001)
    assert t_const_loss == pytest.approx(240.35662592089085, rel=0.001)
    assert cs.coast_t_final_k == pytest.approx(245.57321183820113, rel=0.001)
    assert cs.coast_t_final_k > t_const_loss
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


LUKE_DESIGN_BLOCKERS = sorted(
    [
        "battery.cell_nominal_voltage_v",
        "battery.packaging_insulation_mass_factor",
        "geometry.bottom_radiates_to (Whether box bottom sees regolith or lander deck)",
        "geometry.box_height_m",
        "geometry.box_length_m",
        "geometry.box_width_m",
        "geometry.n_packs",
        "lander_legs.footpad_area_m2",
        "lander_legs.leg_cross_section_m2",
        "lander_legs.leg_length_m",
        "lander_legs.leg_perimeter_m",
        "lander_legs.leg_surface_emissivity",
        "losses.passthrough_w",
        "radiator.louver_area_multiplier",
        "radiator.radiator_areal_mass_kg_per_m2",
        "radiator.radiator_closed_emissivity",
        "radiator.radiator_emissivity",
        "radiator.radiator_temperature_k",
        "wake_up.panel_areal_mass_kg_per_m2",
        "wake_up.panel_efficiency",
        "wake_up.sun_incidence_cosine",
    ]
)


def test_luke_config_has_21_cli_blockers():
    luke = load_config(LUKE_CFG)
    got = sorted(design_blockers(luke))
    assert len(got) == 21
    assert got == LUKE_DESIGN_BLOCKERS
    with pytest.raises(DesignInputError) as err:
        validate_for_run(luke)
    assert sorted(err.value.missing) == LUKE_DESIGN_BLOCKERS


def test_break_even_hand_calc_n8(example_cfg):
    eta_dis = 0.9
    q_closed = 285.8 + 30.494
    p_exp = q_closed / (1.0 / eta_dis - 1.0)
    prim = solve_case("primary_5000W", 5000, 200, example_cfg, case_branch="primary")
    assert prim.break_even_load_w == pytest.approx(p_exp, rel=0.001)


def test_cold_margin_alert_at_n16(example_cfg):
    cfg = copy.deepcopy(example_cfg)
    cfg["geometry"]["n_packs"]["value"] = 16
    prim = solve_case("primary_5000W", 5000, 200, cfg, case_branch="primary")
    cs = solve_cold_shutdown_case(cfg, prim)
    assert cs.coast_margin_lipo_k == pytest.approx(0.238, abs=0.001)
    assert cs.cold_margin_alert is True
    warm = run_n_packs_sensitivity(cfg, specific_energy=200, n_list=(16,))[0]
    assert warm["warm_fleet_kwh"] == pytest.approx(30.07, rel=0.001)


def test_cold_shutdown_stuck_open_n8(example_cfg):
    prim = solve_case("primary_5000W", 5000, 200, example_cfg, case_branch="primary")
    cs = solve_cold_shutdown_case(example_cfg, prim)
    mass_pp = prim.battery.mass_kg / max(1, prim.thermal.n_packs)
    bare = prim.thermal.radiator_bare_area_per_pack_m2
    e_rad = 0.92
    t_sink = effective_sink_temperature_k(3.0, 40.0)
    t0 = 273.15
    q_box_leg_pp = thermal_q_loss_at_box_t(
        example_cfg, t0, fleet_capacity_wh=500_000.0, q_excess_per_pack_w=prim.q_excess_w / 8
    )
    q_rad_open = e_rad * SIGMA_DEFAULT * bare * max(0.0, t0**4 - t_sink**4)
    q0 = q_box_leg_pp + q_rad_open
    t_hand_const = t0 - q0 * 72.0 * 3600.0 / (mass_pp * 1000.0)
    assert mass_pp == pytest.approx(312.5, rel=1e-6)
    assert cs.coast_t_final_k == pytest.approx(245.57321183820113, rel=0.001)
    assert cs.coast_stuck_open_t_final_k == pytest.approx(230.70323875995143, rel=0.001)
    assert t_hand_const < cs.coast_stuck_open_t_final_k
    assert cs.coast_stuck_open_t_final_k < cs.coast_t_final_k
    assert cs.coast_stuck_open_margin_lipo_k == pytest.approx(cs.coast_stuck_open_t_final_k - 233.0, rel=0.001)
    assert cs.louvers_stuck_below_lipo is True


def _pdf_sweep_rows_by_n(pdf_text: str) -> dict[int, str]:
    """Map n_packs (1,2,4,8,16) to the extracted PDF line for that sweep row."""
    want = {1, 2, 4, 8, 16}
    found: dict[int, str] = {}
    for line in pdf_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        head = stripped.split(None, 1)[0]
        try:
            n = int(head)
        except ValueError:
            continue
        if n in want:
            found[n] = stripped
    return found


def test_report_pdf_sweep_includes_dLiPo_so_and_flags(example_cfg, tmp_path):
    pytest.importorskip("pypdf")
    from pypdf import PdfReader

    results = run_all_cases(example_cfg)
    sens = run_n_packs_sensitivity(example_cfg, specific_energy=200, n_list=(1, 2, 4, 8, 16))
    table = format_n_packs_table(sens, example_cfg)
    data_lines = [ln for ln in table.splitlines() if ln.strip() and ln.lstrip()[0].isdigit()]
    assert "dLiPo_so" in table
    assert all(len(ln) >= 110 for ln in data_lines)
    assert all(ln.rstrip().endswith("*") for ln in data_lines)
    assert any("!" in ln for ln in data_lines)

    pdf = tmp_path / "sweep_flags.pdf"
    write_report_pdf(pdf, example_cfg, results, [], todo_luke_list(example_cfg), n_pack_rows=sens)
    text = "\n".join((page.extract_text() or "") for page in PdfReader(pdf).pages)
    assert "dLiPo_so" in text
    assert "stuck-open below LiPo" in text
    rows = _pdf_sweep_rows_by_n(text)
    assert set(rows) == {1, 2, 4, 8, 16}
    for n in (1, 2, 4, 8):
        assert rows[n].endswith("*"), f"n={n} row missing trailing *: {rows[n]!r}"
    assert rows[16].endswith("!*"), f"n=16 row missing !*: {rows[16]!r}"
    assert "BELOW LiPo limit" in text


def test_sweep_glyph_width_scale_derived_from_font_size():
    ref = sweep_pdf_glyph_width_scale(N_PACK_SWEEP_FONT_SIZE)
    assert ref == pytest.approx(SWEEP_PDF_GLYPH_WIDTH_SCALE)
    assert sweep_pdf_glyph_width_scale(N_PACK_SWEEP_FONT_SIZE * 2) == pytest.approx(ref * 2)


def test_report_pdf_sweep_text_fits_page_width(example_cfg, tmp_path, monkeypatch):
    import matplotlib.pyplot as plt

    captured_figs: list = []

    class _CapturingPdfPages:
        def __init__(self, path, *args, **kwargs):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def savefig(self, fig, *args, **kwargs):
            captured_figs.append(fig)

    monkeypatch.setattr("matplotlib.backends.backend_pdf.PdfPages", _CapturingPdfPages)

    results = run_all_cases(example_cfg)
    sens = run_n_packs_sensitivity(example_cfg, specific_energy=200, n_list=(1, 2, 4, 8, 16))
    write_report_pdf(
        tmp_path / "layout_probe.pdf",
        example_cfg,
        results,
        [],
        todo_luke_list(example_cfg),
        n_pack_rows=sens,
    )
    sweep_figs = [f for f in captured_figs if f.get_label() == SWEEP_PDF_PAGE_LABEL]
    assert sweep_figs, "write_report_pdf did not emit an n-packs sweep figure"
    # Agg extents understate PDF width (see sweep_pdf_glyph_width_scale); cap at ~0.91 page width
    # (~1 monospace char slack at 7.5pt/100dpi — tighten if sweep columns are added).
    try:
        for fig in sweep_figs:
            w_px, extents = figure_text_extents_pdf_scaled(fig)
            xmin = 0.04 * w_px
            xmax = 0.91 * w_px
            for x0, x1, _ in extents:
                assert x0 >= xmin - 0.5, f"text left margin too small: x0={x0} min={xmin}"
                assert x1 <= xmax + 0.5, (
                    f"text exceeds PDF-adjusted page width: x1={x1} limit={xmax} "
                    f"(scale={SWEEP_PDF_GLYPH_WIDTH_SCALE})"
                )
    finally:
        for fig in captured_figs:
            plt.close(fig)

