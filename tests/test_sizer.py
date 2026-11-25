"""Hand-checked closed-form and end-to-end tests."""

from pathlib import Path

import pytest
import yaml

from sizer import (
    ConfigError,
    DesignInputError,
    analytic_constant_h_fin_w,
    compute_night_energy_wh,
    compute_pack_mass_kg,
    compute_required_capacity_wh,
    compute_series_count,
    discharge_efficiency_for_sizing,
    end_face_exposure_factor,
    finite_difference_constant_h_fin_w,
    heater_shortfall_w,
    internal_waste_heat_w,
    leg_conduction_network_w,
    load_config,
    blocking_missing,
    net_rtg_need_w,
    per_box_face_areas_m2,
    pick_internal_heat,
    radiation_loss_w,
    regolith_spreading_resistance_k_per_w,
    solve_case,
    solve_radiating_leg_fin,
    total_ring_radiating_area_m2,
    validate_for_run,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "example_config.yaml"
LUKE_CFG = ROOT / "config.yaml"

FIN_BENCH = dict(k_leg=6.7, a_cross=0.001, perimeter_m=0.126, length_m=1.0, t_root=350.0, t_inf=40.0, h_lin=2.0)


@pytest.fixture
def example_cfg():
    return load_config(EXAMPLE)


def test_night_energy_wh():
    assert compute_night_energy_wh(5000, 0, 72) == 360_000


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


def test_eta_definition_blocks_luke_config():
    with pytest.raises(DesignInputError):
        validate_for_run(load_config(LUKE_CFG))


def test_ring_area_eight_boxes():
    total, _ = total_ring_radiating_area_m2(8, 1.0, 0.8, 0.6, 3.0)
    assert total == pytest.approx(30.08, rel=1e-4)


def test_regolith_spreading_disk_formula():
    a_pad = 0.05
    k = 7.4e-4
    r = regolith_spreading_resistance_k_per_w(a_pad, k)
    radius = (a_pad / 3.141592653589793) ** 0.5
    assert r == pytest.approx(1.0 / (4 * k * radius), rel=1e-6)


def test_leg_conduction_hand_calc():
    q = leg_conduction_network_w(
        n_legs=4, k_leg=6.7, a_cross=0.001, length_m=1.0, t_box_k=273.15, t_surface_k=40.0,
        footpad_area=0.05, h_contact=10.0, k_regolith=7.4e-4,
    )
    r_leg = 1.0 / (6.7 * 0.001)
    r_c = 1.0 / (10 * 0.05)
    import math

    a = math.sqrt(0.05 / math.pi)
    r_r = 1.0 / (4 * 7.4e-4 * a)
    expected = 4 * (273.15 - 40) / (r_leg + r_c + r_r)
    assert q == pytest.approx(expected, rel=1e-4)


def test_constant_h_fin_analytic_fd_tanh():
    qa = analytic_constant_h_fin_w(**FIN_BENCH)
    assert qa == pytest.approx(12.84, rel=0.02)
    q12 = finite_difference_constant_h_fin_w(**FIN_BENCH, n_nodes=12)
    q50 = finite_difference_constant_h_fin_w(**FIN_BENCH, n_nodes=50)
    assert q12 == pytest.approx(13.32, rel=0.03)
    assert q50 == pytest.approx(12.86, rel=0.08)
    assert q50 == pytest.approx(qa, rel=0.10)


def test_radiating_leg_example_nodes_and_foot():
    sigma = 5.670374419e-8
    q12, tf12, _ = solve_radiating_leg_fin(
        6.7, 0.001, 0.126, 1.0, 0.9, 273.15, 3, 40, 40, 0.5, 0.5, 0.05, 10, 7.4e-4, 12, sigma
    )
    q50, tf50, _ = solve_radiating_leg_fin(
        6.7, 0.001, 0.126, 1.0, 0.9, 273.15, 3, 40, 40, 0.5, 0.5, 0.05, 10, 7.4e-4, 50, sigma
    )
    assert 4 * q12 == pytest.approx(20.4, rel=0.08)
    assert tf12 == pytest.approx(111.0, rel=0.05)
    assert abs(4 * q12 - 4 * q50) / (4 * q12) < 0.08


def test_example_primary_thermal_targets(example_cfg):
    r = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    assert r.thermal.q_leg_w == pytest.approx(21.7, rel=0.08)
    assert r.thermal.q_total_w == pytest.approx(210.0, rel=0.06)
    assert r.q_excess_w == pytest.approx(60.0, rel=0.08)
    qd = internal_waste_heat_w(5000, 0.9)
    assert r.q_internal_w == qd["round_trip_definition"]


def test_same_pack_reuses_primary_mass(example_cfg):
    prim = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    surv = solve_case(
        "survival_100W", 100, 200, example_cfg,
        fallback_branch="same_pack_survival", primary_pack=prim.battery, transient_mass_kg=prim.battery.mass_kg,
    )
    assert surv.battery.mass_kg == pytest.approx(prim.battery.mass_kg)
    assert surv.battery.capacity_wh == pytest.approx(prim.battery.capacity_wh)
    assert surv.transient_delta_t_k == pytest.approx(-24.0, rel=0.15)


def test_fixed_rtg_heater_iteration(example_cfg):
    cfg = yaml.safe_load(yaml.dump(example_cfg))
    cfg["meta"]["mode"] = "fixed_rtg"
    cfg["rtg"]["thermal_output_w"]["value"] = 10.0
    r = solve_case("survival_100W", 100, 200, cfg, fallback_branch="same_pack_survival",
                   primary_pack=solve_case("primary_5000W", 5000, 200, cfg).battery)
    assert r.battery.p_heater_w == pytest.approx(218, rel=0.12)
    assert r.battery.e_night_wh > 15_000


def test_fixed_rtg_requires_thermal_output(example_cfg):
    bad = yaml.safe_load(yaml.dump(example_cfg))
    bad["meta"]["mode"] = "fixed_rtg"
    bad["rtg"]["thermal_output_w"]["value"] = None
    with pytest.raises(ConfigError):
        validate_for_run(bad)


def test_zero_boxes_raises(example_cfg):
    bad = yaml.safe_load(yaml.dump(example_cfg))
    bad["geometry"]["n_battery_boxes"]["value"] = 0
    with pytest.raises(ConfigError):
        validate_for_run(bad)


def test_solve_case_end_to_end(example_cfg):
    r = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    assert r.q_rtg_total_w is not None


def test_net_rtg_clamps_and_excess():
    q_rtg, excess = net_rtg_need_w(100, 150, 0.5)
    assert q_rtg == 0.0
    assert excess == 50.0


def test_heater_shortfall_includes_internal():
    assert heater_shortfall_w(1000, 200, 1.0, 500) == 300


def test_end_face_reduction_when_gap_small():
    f = end_face_exposure_factor(8, 1.0, 1.0, 0.8)
    assert f == 0.0