"""Shared pytest fixtures for config paths and labels."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from sizer import load_config, param_value

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "example_config.yaml"
LUKE_CFG = ROOT / "config.yaml"

# Required design paths that were null in Luke's pre-approval config.yaml (blocker regression).
LEGACY_DESIGN_BLOCKER_PATHS = sorted(
    [
        "battery.cell_nominal_voltage_v",
        "battery.packaging_insulation_mass_factor",
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


def primary_load_label(cfg) -> str:
    """Match sizer load_name convention: primary_<W>W from config primary_w."""
    w = float(param_value(cfg, "loads", "primary_w"))
    wi = int(w) if w == int(w) else w
    return f"primary_{wi}W"


def clear_config_path(cfg: dict, dotted: str) -> None:
    parts = dotted.split(".")
    node = cfg
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]]["value"] = None


def make_incomplete_blocked_cfg(base: dict | None = None) -> dict:
    """Null the 20 legacy design blockers; default base is Luke's approved config.yaml."""
    cfg = copy.deepcopy(base or load_config(LUKE_CFG))
    for path in LEGACY_DESIGN_BLOCKER_PATHS:
        clear_config_path(cfg, path)
    return cfg


@pytest.fixture
def example_cfg():
    return load_config(EXAMPLE)


@pytest.fixture
def luke_cfg():
    return load_config(LUKE_CFG)


@pytest.fixture
def incomplete_blocked_cfg(luke_cfg):
    return make_incomplete_blocked_cfg(luke_cfg)


@pytest.fixture
def blocked_config_path(tmp_path, incomplete_blocked_cfg):
    path = tmp_path / "blocked_design_config.yaml"
    path.write_text(yaml.dump(incomplete_blocked_cfg), encoding="utf-8")
    return path