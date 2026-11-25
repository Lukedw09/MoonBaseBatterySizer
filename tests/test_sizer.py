"""Hand-checked closed-form and end-to-end tests."""

from pathlib import Path

import pytest
import yaml

from sizer import (
    ConfigError,
    DesignInputError,
    compute_night_energy_wh,
    compute_pack_mass_kg,
    compute_required_capacity_wh,
    compute_series_count,
    end_face_exposure_factor,
    heater_shortfall_w,
    internal_waste_heat_w,
    leg_conduction_network_w,
    load_config,
    blocking_missing,
    net_rtg_need_w,
    per_box_face_areas_m2,
    radiation_loss_w,
    regolith_spreading_resistance_k_per_w,
    solve_case,
    total_ring_radiating_area_m2,
    validate_for_run,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "example_config.yaml"
LUKE_CFG = ROOT / "config.yaml"


@pytest.fixture
def example_cfg():
    return load_config(EXAMPLE)


def test_night_energy_wh():
    assert compute_night_energy_wh(5000, 0, 72) == 360_000


def test_capacity_uses_discharge_eta():
    e = 360_000
    eta_dis = 0.9**0.5
    assert compute_required_capacity_wh(e, 0.8, eta_dis) == pytest.approx(e / (0.8 * eta_dis))


def test_pack_mass():
    assert compute_pack_mass_kg(500_000, 200, 1.0) == 2500


def test_series_count():
    assert compute_series_count(1000, 3.7) == 271


def test_ring_area_eight_boxes():
    total, _ = total_ring_radiating_area_m2(8, 1.0, 0.8, 0.6, 3.0)
    assert total == pytest.approx(30.08, rel=1e-4)


def test_per_box_faces():
    areas = per_box_face_areas_m2(1.0, 0.8, 0.6, end_factor=1.0)
    assert sum(areas.values()) == pytest.approx(3.76, rel=1e-4)


def test_regolith_spreading_disk_formula():
    a_pad = 0.05
    k = 7.4e-4
    r = regolith_spreading_resistance_k_per_w(a_pad, k)
    radius = (a_pad / 3.141592653589793) ** 0.5
    assert r == pytest.approx(1.0 / (4 * k * radius), rel=1e-6)


def test_leg_conduction_hand_calc():
    q = leg_conduction_network_w(
        n_legs=4,
        k_leg=6.7,
        a_cross=0.001,
        length_m=1.0,
        t_box_k=273.15,
        t_surface_k=40.0,
        footpad_area=0.05,
        h_contact=10.0,
        k_regolith=7.4e-4,
    )
    r_leg = 1.0 / (6.7 * 0.001)
    r_c = 1.0 / (10 * 0.05)
    import math

    a = math.sqrt(0.05 / math.pi)
    r_r = 1.0 / (4 * 7.4e-4 * a)
    expected = 4 * (273.15 - 40) / (r_leg + r_c + r_r)
    assert q == pytest.approx(expected, rel=1e-4)


def test_internal_heat_round_trip():
    q = internal_waste_heat_w(5000, 0.9, "round_trip")
    assert q["round_trip_definition"] == pytest.approx(5000 * (1 / 0.9**0.5 - 1), rel=1e-6)


def test_net_rtg_clamps_and_excess():
    q_rtg, excess = net_rtg_need_w(100, 150, 0.5)
    assert q_rtg == 0.0
    assert excess == 50.0


def test_net_rtg_with_coupling_unset():
    q_rtg, excess = net_rtg_need_w(200, 50, None)
    assert q_rtg is None
    assert excess == 0.0


def test_coupling_zero_raises():
    with pytest.raises(ConfigError):
        net_rtg_need_w(100, 0, 0.0)


def test_zero_boxes_raises_on_thermal(example_cfg):
    bad = yaml.safe_load(yaml.dump(example_cfg))
    bad["geometry"]["n_battery_boxes"]["value"] = 0
    with pytest.raises(ConfigError):
        validate_for_run(bad)


def test_zero_legs_raises(example_cfg):
    bad = yaml.safe_load(yaml.dump(example_cfg))
    bad["lander_legs"]["n_legs"]["value"] = 0
    with pytest.raises(ConfigError):
        validate_for_run(bad)


def test_luke_config_stops():
    cfg = load_config(LUKE_CFG)
    with pytest.raises(DesignInputError):
        validate_for_run(cfg)


def test_fixed_rtg_requires_thermal_output(example_cfg):
    bad = yaml.safe_load(yaml.dump(example_cfg))
    bad["meta"]["mode"] = "fixed_rtg"
    bad["rtg"]["thermal_output_w"]["value"] = None
    with pytest.raises(ConfigError):
        validate_for_run(bad)


def test_solve_case_end_to_end(example_cfg):
    r = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    eta_dis = 0.9**0.5
    expected_mass = (360_000 / (0.8 * eta_dis)) / 200
    assert r.battery.mass_kg == pytest.approx(expected_mass, rel=0.01)
    assert r.thermal.q_total_w > 0
    assert r.q_rtg_total_w is not None and r.q_rtg_total_w >= 0
    assert r.q_internal_w > 0


def test_solve_case_primary_load_more_internal_than_survival(example_cfg):
    r_hi = solve_case("primary_5000W", 5000, 200, example_cfg, fallback_branch="primary")
    r_lo = solve_case("survival_50W", 50, 200, example_cfg, fallback_branch="same_pack_survival")
    assert r_hi.q_internal_w > r_lo.q_internal_w
    assert r_hi.q_excess_w >= 0


def test_fixed_rtg_mode_iteration(example_cfg):
    cfg = yaml.safe_load(yaml.dump(example_cfg))
    cfg["meta"]["mode"] = "fixed_rtg"
    cfg["rtg"]["thermal_output_w"]["value"] = 10.0
    r = solve_case("primary_5000W", 5000, 200, cfg, fallback_branch="primary")
    assert r.mode == "fixed_rtg"
    assert r.q_rtg_total_w == 10.0


def test_fallback_both_branches_when_unset(example_cfg):
    from sizer import run_all_cases

    cfg = yaml.safe_load(yaml.dump(example_cfg))
    cfg["fallback"]["mode"]["value"] = None
    results = run_all_cases(cfg)
    branches = {x.fallback_branch for x in results if "survival" in x.load_name}
    assert "same_pack_survival" in branches
    assert "separate_pack" in branches


def test_heater_shortfall_includes_internal():
    assert heater_shortfall_w(1000, 200, 1.0, 500) == 300


def test_radiation_zero_at_uniform_temperature():
    q = radiation_loss_w(0.02, 10.0, 273.15, 273.15, 273.15, 0.5, 0.5)
    assert q == 0.0


def test_end_face_reduction_when_gap_small():
    # 8 boxes at R=1m -> arc = pi/4 ~ 0.785, L=1 -> gap negative, factor 0
    f = end_face_exposure_factor(8, 1.0, 1.0, 0.8)
    assert f == 0.0


def test_missing_list_includes_coupling():
    cfg = load_config(LUKE_CFG)
    missing = blocking_missing(cfg)
    assert any("rtg.coupling_fraction" in m for m in missing)