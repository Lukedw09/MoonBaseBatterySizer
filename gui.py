#!/usr/bin/env python3
"""Tkinter desktop UI for Moon Base pack + radiator sizer (EXAMPLE config by default)."""

from __future__ import annotations

import copy
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

from sizer import (
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
    write_report_pdf,
)

EXAMPLE = Path(__file__).resolve().parent / "examples" / "example_config.yaml"

# Maps stable UI control id -> YAML param path (for tests and apply_if_changed).
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
    """True when design is incomplete — matches Streamlit gate (blockers first, then validate_for_run)."""
    blockers = design_blockers(cfg)
    if blockers:
        return True, blockers
    try:
        validate_for_run(cfg)
    except DesignInputError as e:
        return True, list(e.missing)
    return False, []


def collect_ui_values(controls: Dict[str, tk.Variable]) -> Dict[Tuple[str, ...], Any]:
    """Read widget variables into cfg key tuples (same set app.py wrote)."""
    values: Dict[Tuple[str, ...], Any] = {}
    for ui_id, keys in UI_CONTROL_TO_CFG_KEYS.items():
        raw = controls[ui_id].get()
        values[keys] = int(raw) if ui_id == "n_packs" else float(raw)
    return values


def apply_ui_values(base_cfg: dict, cfg: dict, controls: Dict[str, tk.Variable]) -> None:
    for keys, val in collect_ui_values(controls).items():
        apply_if_changed(base_cfg, cfg, *keys, new_value=val)


def _require_param(cfg: dict, *keys: str) -> Any:
    v = param_value(cfg, *keys)
    if v is None:
        raise DesignInputError([f"{'.'.join(keys)}"])
    return v


class SizerGUI:
    def __init__(self, root: tk.Tk, *, config_path: Optional[Path] = None) -> None:
        self.root = root
        self.root.title("Moon Base Battery Sizer")
        self.root.minsize(960, 640)
        self.base_cfg: Optional[dict] = None
        self.cfg: Optional[dict] = None
        self.last_results = None
        self.last_sens = None
        self.controls: Dict[str, tk.Variable] = {}
        self._owner_labels: Dict[str, tk.Label] = {}
        self._tuning_widgets: List[tk.Widget] = []

        top = ttk.Frame(root, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Config YAML:").pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value=str(config_path or EXAMPLE))
        ttk.Entry(top, textvariable=self.path_var, width=60).pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        ttk.Button(top, text="Load config", command=self.load_config).pack(side=tk.LEFT)

        paned = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left_outer = ttk.Frame(paned)
        paned.add(left_outer, weight=1)
        canvas = tk.Canvas(left_outer, highlightthickness=0)
        scroll = ttk.Scrollbar(left_outer, orient=tk.VERTICAL, command=canvas.yview)
        self.tuning_frame = ttk.Frame(canvas, padding=4)
        self.tuning_frame.bind(
            "<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.tuning_frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        right = ttk.Frame(paned, padding=4)
        paned.add(right, weight=2)
        ttk.Label(right, text="Results").pack(anchor=tk.W)
        text_wrap = ttk.Frame(right)
        text_wrap.pack(fill=tk.BOTH, expand=True)
        self.results_text = tk.Text(text_wrap, wrap=tk.NONE, state=tk.DISABLED, font=("Courier", 9))
        yscroll = ttk.Scrollbar(text_wrap, orient=tk.VERTICAL, command=self.results_text.yview)
        xscroll = ttk.Scrollbar(text_wrap, orient=tk.HORIZONTAL, command=self.results_text.xview)
        self.results_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.results_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        text_wrap.rowconfigure(0, weight=1)
        text_wrap.columnconfigure(0, weight=1)

        btn_row = ttk.Frame(right)
        btn_row.pack(fill=tk.X, pady=6)
        self.run_btn = ttk.Button(btn_row, text="Run sizing", command=self.run_sizing)
        self.run_btn.pack(side=tk.LEFT, padx=4)
        self.pdf_btn = ttk.Button(btn_row, text="Save PDF", command=self.save_pdf)
        self.pdf_btn.pack(side=tk.LEFT, padx=4)

        self._build_tuning_controls()
        self.load_config()

    def _add_control(
        self,
        ui_id: str,
        label: str,
        var: tk.Variable,
        *,
        build: Callable[[ttk.Frame, tk.Variable], tk.Widget],
    ) -> None:
        row = ttk.Frame(self.tuning_frame)
        row.pack(fill=tk.X, pady=2)
        ttk.Label(row, text=label, width=28).pack(side=tk.LEFT, anchor=tk.W)
        widget = build(row, var)
        widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
        own = ttk.Label(row, text="", font=("TkDefaultFont", 8), foreground="gray")
        own.pack(side=tk.LEFT, padx=6)
        self._owner_labels[ui_id] = own
        self.controls[ui_id] = var
        self._tuning_widgets.extend([row, widget, own])
        var.trace_add("write", lambda *_: self._refresh_owner_caption(ui_id))

    def _build_tuning_controls(self) -> None:
        ttk.Label(self.tuning_frame, text="Tuning (ui-override only when changed)", font=("TkDefaultFont", 10, "bold")).pack(
            anchor=tk.W, pady=(0, 8)
        )

        def scale(row: ttk.Frame, var: tk.Variable, from_, to, resolution=1.0) -> tk.Widget:
            return tk.Scale(row, variable=var, from_=from_, to=to, resolution=resolution, orient=tk.HORIZONTAL, length=220)

        self._add_control(
            "n_packs",
            "n_packs",
            tk.IntVar(value=8),
            build=lambda r, v: scale(r, v, 1, 16, 1),
        )
        self._add_control(
            "primary_w",
            "Night load (W)",
            tk.DoubleVar(value=5000.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=0, to=20000, width=12),
        )
        self._add_control(
            "t_dark_h",
            "Night hours",
            tk.DoubleVar(value=72.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=1, to=240, increment=0.5, width=12),
        )
        self._add_control(
            "specific_energy_wh_per_kg_low",
            "Specific energy low (Wh/kg)",
            tk.DoubleVar(value=150.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=50, to=400, width=12),
        )
        self._add_control(
            "specific_energy_wh_per_kg_high",
            "Specific energy high (Wh/kg)",
            tk.DoubleVar(value=200.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=50, to=400, width=12),
        )
        self._add_control(
            "pack_volumetric_energy_density_wh_per_m3",
            "Pack volumetric density (Wh/m³)",
            tk.DoubleVar(value=250000.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=50000, to=500000, increment=1000, width=12),
        )
        self._add_control(
            "depth_of_discharge",
            "Depth of discharge",
            tk.DoubleVar(value=0.9),
            build=lambda r, v: scale(r, v, 0.1, 1.0, 0.01),
        )
        self._add_control(
            "efficiency",
            "Discharge η",
            tk.DoubleVar(value=0.9),
            build=lambda r, v: scale(r, v, 0.5, 1.0, 0.01),
        )
        self._add_control(
            "packaging_insulation_mass_factor",
            "Packaging factor",
            tk.DoubleVar(value=1.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=0.5, to=3.0, increment=0.05, width=12),
        )
        self._add_control(
            "box_target_temperature_k",
            "T_box (K)",
            tk.DoubleVar(value=273.15),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=200, to=310, increment=0.5, width=12),
        )
        self._add_control(
            "radiator_temperature_k",
            "T_rad (K)",
            tk.DoubleVar(value=273.15),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=200, to=310, increment=0.5, width=12),
        )
        self._add_control(
            "radiator_emissivity",
            "Radiator ε",
            tk.DoubleVar(value=0.9),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=0.05, to=1.0, increment=0.01, width=12),
        )
        self._add_control(
            "warm_up_h",
            "Warm-up h",
            tk.DoubleVar(value=6.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=0.5, to=24, increment=0.25, width=12),
        )
        self._add_control(
            "panel_efficiency",
            "Panel η",
            tk.DoubleVar(value=0.28),
            build=lambda r, v: scale(r, v, 0.05, 0.45, 0.01),
        )
        self._add_control(
            "sun_incidence_cosine",
            "cos(incidence)",
            tk.DoubleVar(value=0.35),
            build=lambda r, v: scale(r, v, 0.05, 1.0, 0.01),
        )

    def _refresh_owner_caption(self, ui_id: str) -> None:
        if not self.base_cfg:
            return
        keys = UI_CONTROL_TO_CFG_KEYS[ui_id]
        var = self.controls[ui_id]
        try:
            val = int(var.get()) if ui_id == "n_packs" else float(var.get())
        except tk.TclError:
            return
        self._owner_labels[ui_id].configure(
            text=f"owner: {effective_owner_label(self.base_cfg, *keys, current_value=val)}"
        )

    def _set_tuning_state(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in self._tuning_widgets:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        self.run_btn.configure(state=state)
        self.pdf_btn.configure(state=tk.DISABLED if not enabled else tk.NORMAL)

    def _set_results(self, text: str) -> None:
        self.results_text.configure(state=tk.NORMAL)
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert(tk.END, text)
        self.results_text.configure(state=tk.DISABLED)

    def load_config(self) -> None:
        try:
            path = Path(self.path_var.get().strip())
            self.base_cfg = load_config(path)
        except Exception as e:
            self.base_cfg = None
            self.cfg = None
            self._set_tuning_state(False)
            self._set_results(f"Could not load config:\n{e}")
            return

        blocked, messages = app_gate_blocked(self.base_cfg)
        if blocked:
            self.cfg = None
            self._set_tuning_state(False)
            lines = ["Design incomplete — fix these before tuning or run:\n"]
            lines.extend(f"  • {m}" for m in messages)
            lines.append("\nUse examples/example_config.yaml for a complete EXAMPLE ONLY config.")
            self._set_results("\n".join(lines))
            return

        self.cfg = copy.deepcopy(self.base_cfg)
        self._populate_controls_from_cfg()
        self._set_tuning_state(True)
        self._set_results("Config loaded. Adjust sliders if needed, then click Run sizing.")

    def _populate_controls_from_cfg(self) -> None:
        assert self.base_cfg is not None
        cfg = self.base_cfg
        for ui_id, keys in UI_CONTROL_TO_CFG_KEYS.items():
            val = _require_param(cfg, *keys)
            if ui_id == "n_packs":
                self.controls[ui_id].set(int(val))
            else:
                self.controls[ui_id].set(float(val))
            self._refresh_owner_caption(ui_id)
        t_box = float(self.controls["box_target_temperature_k"].get())
        t_rad = float(self.controls["radiator_temperature_k"].get())
        if t_rad > t_box:
            self.controls["radiator_temperature_k"].set(t_box)

    def _working_cfg(self) -> dict:
        if self.base_cfg is None or self.cfg is None:
            raise RuntimeError("Config not loaded")
        cfg = copy.deepcopy(self.base_cfg)
        apply_ui_values(self.base_cfg, cfg, self.controls)
        return cfg

    def run_sizing(self) -> None:
        blocked, messages = app_gate_blocked(self.base_cfg or {})
        if blocked:
            self._set_results("Blocked:\n" + "\n".join(f"  • {m}" for m in messages))
            return
        try:
            cfg = self._working_cfg()
            validate_for_run(cfg)
            results = run_all_cases(cfg)
            coupling = rtg_module_enabled(cfg) and param_value(cfg, "rtg", "coupling_fraction") is not None
            se_high = float(self.controls["specific_energy_wh_per_kg_high"].get())
            sens = run_n_packs_sensitivity(cfg, specific_energy=se_high, n_list=(1, 2, 4, 8, 16))
            self.last_results = results
            self.last_sens = sens
            text = format_results_table(results, coupling, cfg) + format_n_packs_table(sens, cfg)
            self._set_results(text)
            self.pdf_btn.configure(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("Run failed", str(e))

    def save_pdf(self) -> None:
        if self.last_results is None or self.last_sens is None or self.base_cfg is None:
            messagebox.showinfo("Save PDF", "Run sizing first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile="moon_base_sizer_report.pdf",
        )
        if not path:
            return
        try:
            cfg = self._working_cfg()
            validate_for_run(cfg)
            write_report_pdf(Path(path), cfg, self.last_results, [], [], n_pack_rows=self.last_sens)
            messagebox.showinfo("Save PDF", f"Wrote {path}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))


def main() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"Could not open a desktop window: {e}", file=sys.stderr)
        print(
            "Tkinter may be missing. On Linux try: sudo apt install python3-tk",
            file=sys.stderr,
        )
        sys.exit(1)
    SizerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()