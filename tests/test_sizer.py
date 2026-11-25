"""Hand-checked closed-form tests for lunar base sizer."""

import math

import pytest

from sizer import (
    compute_night_energy_wh,
    compute_pack_mass_kg,
    compute_required_capacity_wh,
    compute_series_count,
    leg_conduction_w,
    radiation_loss_w,
    required_rtg_thermal_w,
    heater_shortfall_w,
)


def test_night_energy_wh():
    # 5000 W * 72 h = 360000 Wh
    assert compute_night_energy_wh(5000, 0, 72) == 360_000


def test_capacity_from_energy():
    # C = E / (0.8 * 0.9) = E / 0.72
    e = 360_000
    assert compute_required_capacity_wh(e, 0.8, 0.9) == pytest.approx(500_000)


def test_pack_mass():
    # 500000 Wh / 200 Wh/kg * 1.0 = 2500 kg
    assert compute_pack_mass_kg(500_000, 200, 1.0) == 2500


def test_series_count():
    assert compute_series_count(1000, 3.7) == 271


def test_radiation_is_zero_when_temperatures_equal():
    q = radiation_loss_w(0.02, 10.0, 273.15, 273.15, 273.15, 0.5, 0.5)
    assert q == 0.0


def test_radiation_scales_with_emittance():
    base = radiation_loss_w(0.02, 5.0, 273.15, 3.0, 40.0, 0.5, 0.5)
    double = radiation_loss_w(0.04, 5.0, 273.15, 3.0, 40.0, 0.5, 0.5)
    assert double == pytest.approx(2 * base)


def test_rtg_required_inverse_coupling():
    assert required_rtg_thermal_w(1000, 0.5) == 2000


def test_heater_shortfall():
    assert heater_shortfall_w(1000, 1.0, 400) == 600
    assert heater_shortfall_w(1000, 1.0, 1200) == 0


def test_leg_conduction_positive_at_warm_box():
    q = leg_conduction_w(
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
    assert q > 0


def test_energy_with_heater_adds_linearly():
    assert compute_night_energy_wh(100, 50, 10) == 1500