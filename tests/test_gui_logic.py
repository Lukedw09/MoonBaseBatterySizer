"""Tests for gui_logic.py (no tkinter required)."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

import pytest

import gui_logic
from sizer import load_config, param_value

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "example_config.yaml"
LUKE_CFG = ROOT / "config.yaml"

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


@pytest.fixture
def example_cfg():
    return load_config(EXAMPLE)


def test_gui_logic_imports_without_tkinter():
    assert gui_logic.UI_CONTROL_TO_CFG_KEYS


def test_default_config_path_prefers_luke_yaml():
    path = gui_logic.default_config_path()
    assert path == LUKE_CFG if LUKE_CFG.is_file() else gui_logic.EXAMPLE_CFG


def test_gui_slider_config_key_map():
    assert set(gui_logic.UI_CONTROL_TO_CFG_KEYS.values()) == EXPECTED_UI_CFG_KEYS
    cfg = load_config(EXAMPLE)
    for ui_id, keys in gui_logic.UI_CONTROL_TO_CFG_KEYS.items():
        assert param_value(cfg, *keys) is not None, ui_id


class _FakeVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


def test_gui_collect_ui_values_matches_config_keys(example_cfg):
    controls = {
        ui_id: _FakeVar(param_value(example_cfg, *keys))
        for ui_id, keys in gui_logic.UI_CONTROL_TO_CFG_KEYS.items()
    }
    got = gui_logic.collect_ui_values(controls)
    assert set(got.keys()) == EXPECTED_UI_CFG_KEYS


def test_gui_ui_override_only_on_change(example_cfg):
    cfg = copy.deepcopy(example_cfg)
    keys = ("loads", "primary_w")
    base = float(param_value(example_cfg, *keys))
    controls = {
        ui_id: _FakeVar(param_value(example_cfg, *k))
        for ui_id, k in gui_logic.UI_CONTROL_TO_CFG_KEYS.items()
    }
    gui_logic.apply_ui_values(example_cfg, cfg, controls)
    assert param_value(cfg, *keys) == base
    assert "ui-override" not in (cfg["loads"]["primary_w"].get("owner") or "")

    controls["primary_w"] = _FakeVar(base + 100.0)
    gui_logic.apply_ui_values(example_cfg, cfg, controls)
    assert param_value(cfg, *keys) == base + 100.0
    assert cfg["loads"]["primary_w"]["owner"].startswith("ui-override")


def test_gui_blocker_gate_blocks_luke_config():
    blocked, messages = gui_logic.app_gate_blocked(load_config(LUKE_CFG))
    assert blocked
    assert len(messages) == 21


def test_gui_blocker_gate_allows_example_config(example_cfg):
    blocked, messages = gui_logic.app_gate_blocked(example_cfg)
    assert not blocked
    assert messages == []


def test_effective_owner_label_includes_was_prior():
    cfg = load_config(EXAMPLE)
    label = gui_logic.effective_owner_label(cfg, "loads", "primary_w", current_value=6000.0)
    assert "ui-override" in label
    assert "was" in label
    assert "luke" in label


def test_ui_override_owner_tag_in_working_cfg(example_cfg):
    cfg = copy.deepcopy(example_cfg)
    controls = {
        ui_id: _FakeVar(param_value(example_cfg, *keys))
        for ui_id, keys in gui_logic.UI_CONTROL_TO_CFG_KEYS.items()
    }
    controls["primary_w"] = _FakeVar(6000.0)
    working = gui_logic.build_working_cfg(example_cfg, controls)
    assert working["loads"]["primary_w"]["owner"].startswith("ui-override")
    assert "was" in working["loads"]["primary_w"]["owner"]


def test_app_gate_blocks_radiator_above_box_temperature(example_cfg):
    cfg = copy.deepcopy(example_cfg)
    cfg["radiator"]["radiator_temperature_k"]["value"] = float(cfg["battery"]["box_target_temperature_k"]["value"]) + 1.0
    blocked, messages = gui_logic.app_gate_blocked(cfg)
    assert blocked
    assert any("radiator_temperature_k" in m for m in messages)
    assert any("≤" in m or "<=" in m for m in messages)


def test_parse_ui_n_packs_range_and_integer():
    with pytest.raises(gui_logic.UiInputError, match="integer"):
        gui_logic.parse_ui_control_value("n_packs", "abc")
    with pytest.raises(gui_logic.UiInputError, match="512"):
        gui_logic.parse_ui_control_value("n_packs", 600)
    assert gui_logic.parse_ui_control_value("n_packs", "32") == 32


def test_pytest_gui_logic_passes_with_tkinter_blocked_subprocess():
    """Logic tests must not import tkinter; simulate missing tkinter and run this file."""
    logic_tests = str(ROOT / "tests" / "test_gui_logic.py")
    code = f"""
import sys
sys.modules['tkinter'] = None
sys.modules['tkinter.ttk'] = None
import pytest
raise SystemExit(pytest.main([{logic_tests!r}, '-q',
    '-k', 'not passes_with_tkinter_blocked_subprocess']))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr