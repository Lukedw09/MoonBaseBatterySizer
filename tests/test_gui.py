"""Tests for gui.py (Tkinter desktop UI)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sizer import load_config, param_value

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "example_config.yaml"
LUKE_CFG = ROOT / "config.yaml"


@pytest.fixture
def example_cfg():
    return load_config(EXAMPLE)

EXPECTED_UI_CFG_KEYS = {
    ("geometry", "n_packs"),
    ("loads", "primary_w"),
    ("night", "t_dark_h"),
    ("battery", "specific_energy_wh_per_kg_low"),
    ("battery", "specific_energy_wh_per_kg_high"),
    ("battery", "pack_volumetric_energy_density_wh_per_m3"),
    ("battery", "depth_of_discharge"),
    ("battery", "efficiency"),
    ("battery", "packaging_insulation_mass_factor"),
    ("battery", "box_target_temperature_k"),
    ("radiator", "radiator_temperature_k"),
    ("radiator", "radiator_emissivity"),
    ("wake_up", "warm_up_h"),
    ("wake_up", "panel_efficiency"),
    ("wake_up", "sun_incidence_cosine"),
}


def test_gui_module_imports():
    pytest.importorskip("tkinter", reason="tkinter not available (e.g. install python3-tk on Linux)")
    import gui  # noqa: F401

    assert gui.UI_CONTROL_TO_CFG_KEYS


def test_gui_slider_config_key_map():
    import gui

    assert set(gui.UI_CONTROL_TO_CFG_KEYS.values()) == EXPECTED_UI_CFG_KEYS
    for ui_id, keys in gui.UI_CONTROL_TO_CFG_KEYS.items():
        assert param_value(load_config(EXAMPLE), *keys) is not None, ui_id


class _FakeVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


def test_gui_collect_ui_values_matches_config_keys(example_cfg):
    import gui

    controls = {
        ui_id: _FakeVar(param_value(example_cfg, *keys))
        for ui_id, keys in gui.UI_CONTROL_TO_CFG_KEYS.items()
    }
    got = gui.collect_ui_values(controls)
    assert set(got.keys()) == EXPECTED_UI_CFG_KEYS


def test_gui_ui_override_only_on_change(example_cfg):
    import copy

    import gui

    cfg = copy.deepcopy(example_cfg)
    keys = ("loads", "primary_w")
    base = float(param_value(example_cfg, *keys))
    controls = {
        ui_id: _FakeVar(param_value(example_cfg, *k))
        for ui_id, k in gui.UI_CONTROL_TO_CFG_KEYS.items()
    }
    gui.apply_ui_values(example_cfg, cfg, controls)
    assert param_value(cfg, *keys) == base
    assert "ui-override" not in (cfg["loads"]["primary_w"].get("owner") or "")

    controls["primary_w"] = _FakeVar(base + 100.0)
    gui.apply_ui_values(example_cfg, cfg, controls)
    assert param_value(cfg, *keys) == base + 100.0
    assert cfg["loads"]["primary_w"]["owner"].startswith("ui-override")


def test_gui_blocker_gate_blocks_luke_config():
    import gui

    blocked, messages = gui.app_gate_blocked(load_config(LUKE_CFG))
    assert blocked
    assert len(messages) == 22


def test_gui_blocker_gate_allows_example_config(example_cfg):
    import gui

    blocked, messages = gui.app_gate_blocked(example_cfg)
    assert not blocked
    assert messages == []