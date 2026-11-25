"""Non-Tk config/UI logic for the desktop sizer (importable without tkinter)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Mapping, Protocol, Tuple, Union

from sizer import (
    ConfigError,
    DesignInputError,
    design_blockers,
    format_n_packs_table,
    format_results_table,
    load_config,
    param_value,
    run_all_cases,
    run_n_packs_sensitivity,
    rtg_module_enabled,
    validate_for_run,
    validate_radiator_temperature,
    write_report_pdf,
)

ROOT = Path(__file__).resolve().parent
LUKE_CFG = ROOT / "config.yaml"
EXAMPLE_CFG = ROOT / "examples" / "example_config.yaml"

UI_CONTROL_TO_CFG_KEYS: Dict[str, Tuple[str, ...]] = {
    "n_packs": ("geometry", "n_packs"),
    "primary_w": ("loads", "primary_w"),
    "t_dark_h": ("night", "t_dark_h"),
    "specific_energy_wh_per_kg_low": ("battery", "specific_energy_wh_per_kg_low"),
    "specific_energy_wh_per_kg_high": ("battery", "specific_energy_wh_per_kg_high"),
    "pack_volumetric_energy_density_wh_per_m3": (
        "battery",
        "pack_volumetric_energy_density_wh_per_m3",
    ),
    "depth_of_discharge": ("battery", "depth_of_discharge"),
    "efficiency": ("battery", "efficiency"),
    "packaging_insulation_mass_factor": ("battery", "packaging_insulation_mass_factor"),
    "box_target_temperature_k": ("battery", "box_target_temperature_k"),
    "radiator_temperature_k": ("radiator", "radiator_temperature_k"),
    "radiator_emissivity": ("radiator", "radiator_emissivity"),
    "warm_up_h": ("wake_up", "warm_up_h"),
    "panel_efficiency": ("wake_up", "panel_efficiency"),
    "sun_incidence_cosine": ("wake_up", "sun_incidence_cosine"),
}


def default_config_path() -> Path:
    """Luke's config.yaml when present in the repo; otherwise the EXAMPLE path."""
    return LUKE_CFG if LUKE_CFG.is_file() else EXAMPLE_CFG


class _ControlReader(Protocol):
    def get(self) -> Union[int, float, str]: ...


def leaf_owner(cfg: dict, *keys: str) -> str:
    node = cfg
    for k in keys:
        node = node[k]
    if isinstance(node, dict):
        return str(node.get("owner") or "")
    return ""


def effective_owner_label(base_cfg: dict, *keys: str, current_value: Any) -> str:
    base_val = param_value(base_cfg, *keys)
    prior = leaf_owner(base_cfg, *keys) or "unknown"
    if base_val is not None and current_value == base_val:
        return prior
    if prior.startswith("ui-override"):
        return prior
    return f"ui-override (was {prior})"


def apply_if_changed(base_cfg: dict, cfg: dict, *keys: str, new_value: Any) -> None:
    base_val = param_value(base_cfg, *keys)
    path = cfg
    for k in keys[:-1]:
        path = path[k]
    leaf = path[keys[-1]]
    if not isinstance(leaf, dict):
        path[keys[-1]] = new_value
        return
    if base_val is not None and new_value == base_val:
        return
    prior = leaf.get("owner") or "unknown"
    leaf["value"] = new_value
    leaf["owner"] = f"ui-override (was {prior})" if prior != "ui-override" else "ui-override"


def app_gate_blocked(cfg: dict) -> Tuple[bool, List[str]]:
    """True when design is incomplete — blockers first, then validate_for_run."""
    blockers = design_blockers(cfg)
    if blockers:
        return True, blockers
    try:
        validate_for_run(cfg)
    except DesignInputError as e:
        return True, list(e.missing)
    try:
        validate_radiator_temperature(cfg)
    except ConfigError as e:
        return True, [str(e)]
    return False, []


def collect_ui_values(control_values: Mapping[str, Any]) -> Dict[Tuple[str, ...], Any]:
    """Map UI control ids to YAML param paths (values from widgets or test fakes)."""
    out: Dict[Tuple[str, ...], Any] = {}
    for ui_id, keys in UI_CONTROL_TO_CFG_KEYS.items():
        raw = control_values[ui_id]
        if callable(getattr(raw, "get", None)):
            raw = raw.get()
        out[keys] = int(raw) if ui_id == "n_packs" else float(raw)
    return out


def apply_ui_values(base_cfg: dict, cfg: dict, control_values: Mapping[str, Any]) -> None:
    for keys, val in collect_ui_values(control_values).items():
        apply_if_changed(base_cfg, cfg, *keys, new_value=val)


def require_param(cfg: dict, *keys: str) -> Any:
    v = param_value(cfg, *keys)
    if v is None:
        raise DesignInputError([f"{'.'.join(keys)}"])
    return v


def build_working_cfg(base_cfg: dict, control_values: Mapping[str, Any]) -> dict:
    cfg = copy.deepcopy(base_cfg)
    apply_ui_values(base_cfg, cfg, control_values)
    return cfg


def run_sizing_report(
    base_cfg: dict, control_values: Mapping[str, Any]
) -> Tuple[dict, str, list, list]:
    """Return (working_cfg, text_table, case_results, n_pack_sens rows)."""
    cfg = build_working_cfg(base_cfg, control_values)
    validate_for_run(cfg)
    results = run_all_cases(cfg)
    coupling = rtg_module_enabled(cfg) and param_value(cfg, "rtg", "coupling_fraction") is not None
    se_high = float(collect_ui_values(control_values)[("battery", "specific_energy_wh_per_kg_high")])
    sens = run_n_packs_sensitivity(cfg, specific_energy=se_high, n_list=(1, 2, 4, 8, 16))
    text = format_results_table(results, coupling, cfg) + format_n_packs_table(sens, cfg)
    return cfg, text, results, sens


def write_sizing_pdf(path: Path, cfg: dict, results: list, sens: list) -> None:
    write_report_pdf(path, cfg, results, [], [], n_pack_rows=sens)