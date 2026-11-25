#!/usr/bin/env python3
"""Tkinter desktop UI for Moon Base pack + radiator sizer."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional

from gui_logic import (
    EXAMPLE_CFG,
    UI_CONTROL_TO_CFG_KEYS,
    app_gate_blocked,
    apply_ui_values,
    build_working_cfg,
    default_config_path,
    effective_owner_label,
    load_config,
    require_param,
    run_sizing_report,
    write_sizing_pdf,
)

try:
    import tkinter as tk
except ImportError:  # pragma: no cover - headless CI may lack tkinter
    tk = None  # type: ignore[misc, assignment]


def _horizontal_scale(
    parent: tk.Misc,
    var: tk.Variable,
    *,
    from_: float,
    to: float,
    resolution: float,
    length: int = 220,
) -> tk.Scale:
    digits = 0 if isinstance(var, tk.IntVar) else 3
    return tk.Scale(
        parent,
        variable=var,
        from_=from_,
        to=to,
        resolution=resolution,
        orient=tk.HORIZONTAL,
        length=length,
        showvalue=True,
        digits=digits,
        sliderrelief=tk.RAISED,
        sliderlength=28,
        borderwidth=1,
    )


class SizerGUI:
    def __init__(self, root: tk.Tk, *, config_path: Optional[Path] = None) -> None:
        self.root = root
        self.root.title("Moon Base Battery Sizer")
        self.root.minsize(960, 640)
        self.base_cfg: Optional[dict] = None
        self.loaded_path: Optional[Path] = None
        self.last_results = None
        self.last_sens = None
        self.last_working_cfg: Optional[dict] = None
        self.controls: Dict[str, tk.Variable] = {}
        self._scales: Dict[str, tk.Scale] = {}
        self._owner_labels: Dict[str, tk.Label] = {}
        self._tuning_widgets: List[tk.Widget] = []

        top = ttk.Frame(root, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Config YAML:").pack(side=tk.LEFT)
        start_path = config_path if config_path is not None else default_config_path()
        self.path_var = tk.StringVar(value=str(start_path))
        ttk.Entry(top, textvariable=self.path_var, width=60).pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        ttk.Button(top, text="Load config", command=self.load_config).pack(side=tk.LEFT)
        self.loaded_label = ttk.Label(top, text="", font=("TkDefaultFont", 9, "italic"))
        self.loaded_label.pack(side=tk.LEFT, padx=8)

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
        self.pdf_btn = ttk.Button(btn_row, text="Save PDF", command=self.save_pdf, state=tk.DISABLED)
        self.pdf_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Load EXAMPLE config…", command=self._pick_example_config).pack(
            side=tk.LEFT, padx=4
        )

        self._build_tuning_controls()
        self.load_config()

    def _pick_example_config(self) -> None:
        self.path_var.set(str(EXAMPLE_CFG))
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
        if isinstance(widget, tk.Scale):
            widget.pack(side=tk.LEFT, fill=tk.NONE, expand=False)
        else:
            widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
        own = ttk.Label(row, text="", font=("TkDefaultFont", 8), foreground="gray")
        own.pack(side=tk.LEFT, padx=6)
        self._owner_labels[ui_id] = own
        self.controls[ui_id] = var
        if isinstance(widget, tk.Scale):
            widget.set(float(var.get()) if not isinstance(var, tk.IntVar) else int(var.get()))
            self._scales[ui_id] = widget
        self._tuning_widgets.extend([row, widget, own])
        var.trace_add("write", lambda *_: self._refresh_owner_caption(ui_id))

    def _build_tuning_controls(self) -> None:
        ttk.Label(
            self.tuning_frame,
            text="Tuning (ui-override only when changed)",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        def scale(row: ttk.Frame, var: tk.Variable, from_, to, resolution=1.0) -> tk.Widget:
            return _horizontal_scale(row, var, from_=from_, to=to, resolution=resolution)

        root = self.root

        self._add_control(
            "n_packs",
            "n_packs",
            tk.IntVar(master=root, value=8),
            build=lambda r, v: scale(r, v, 1, 16, 1),
        )
        self._add_control(
            "primary_w",
            "Night load (W)",
            tk.DoubleVar(master=root, value=5000.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=0, to=20000, width=12),
        )
        self._add_control(
            "t_dark_h",
            "Night hours",
            tk.DoubleVar(master=root, value=72.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=1, to=240, increment=0.5, width=12),
        )
        self._add_control(
            "specific_energy_wh_per_kg_low",
            "Specific energy low (Wh/kg)",
            tk.DoubleVar(master=root, value=150.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=50, to=400, width=12),
        )
        self._add_control(
            "specific_energy_wh_per_kg_high",
            "Specific energy high (Wh/kg)",
            tk.DoubleVar(master=root, value=200.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=50, to=400, width=12),
        )
        self._add_control(
            "pack_volumetric_energy_density_wh_per_m3",
            "Pack volumetric density (Wh/m³)",
            tk.DoubleVar(master=root, value=250000.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=50000, to=500000, increment=1000, width=12),
        )
        self._add_control(
            "depth_of_discharge",
            "Depth of discharge",
            tk.DoubleVar(master=root, value=0.8),
            build=lambda r, v: scale(r, v, 0.05, 1.0, 0.01),
        )
        self._add_control(
            "efficiency",
            "Discharge η",
            tk.DoubleVar(master=root, value=0.9),
            build=lambda r, v: scale(r, v, 0.05, 1.0, 0.01),
        )
        self._add_control(
            "packaging_insulation_mass_factor",
            "Packaging factor",
            tk.DoubleVar(master=root, value=1.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=0.5, to=3.0, increment=0.05, width=12),
        )
        self._add_control(
            "box_target_temperature_k",
            "T_box (K)",
            tk.DoubleVar(master=root, value=273.15),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=200, to=310, increment=0.5, width=12),
        )
        self._add_control(
            "radiator_temperature_k",
            "T_rad (K)",
            tk.DoubleVar(master=root, value=273.15),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=200, to=310, increment=0.5, width=12),
        )
        self._add_control(
            "radiator_emissivity",
            "Radiator ε",
            tk.DoubleVar(master=root, value=0.9),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=0.05, to=1.0, increment=0.01, width=12),
        )
        self._add_control(
            "warm_up_h",
            "Warm-up h",
            tk.DoubleVar(master=root, value=6.0),
            build=lambda r, v: ttk.Spinbox(r, textvariable=v, from_=0.5, to=24, increment=0.25, width=12),
        )
        self._add_control(
            "panel_efficiency",
            "Panel η",
            tk.DoubleVar(master=root, value=0.28),
            build=lambda r, v: scale(r, v, 0.05, 0.45, 0.01),
        )
        self._add_control(
            "sun_incidence_cosine",
            "cos(incidence)",
            tk.DoubleVar(master=root, value=0.35),
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
            if isinstance(w, tk.Scale):
                continue
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        self.run_btn.configure(state=state)

    def _set_results(self, text: str) -> None:
        self.results_text.configure(state=tk.NORMAL)
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert(tk.END, text)
        self.results_text.configure(state=tk.DISABLED)

    def _show_loaded_path(self, path: Path) -> None:
        self.loaded_path = path
        self.loaded_label.configure(text=f"Loaded: {path.name}")

    def load_config(self) -> None:
        self.pdf_btn.configure(state=tk.DISABLED)
        self.last_results = None
        self.last_sens = None
        try:
            path = Path(self.path_var.get().strip())
            self.base_cfg = load_config(path)
            self._show_loaded_path(path)
        except Exception as e:
            self.base_cfg = None
            self.loaded_path = None
            self.loaded_label.configure(text="")
            self._set_tuning_state(False)
            self._set_results(f"Could not load config:\n{e}")
            return

        blocked, messages = app_gate_blocked(self.base_cfg)
        if blocked:
            self._set_tuning_state(False)
            lines = [f"Loaded: {path.name}", "", "Design incomplete — fix these before tuning or run:\n"]
            lines.extend(f"  • {m}" for m in messages)
            lines.append("\nUse “Load EXAMPLE config…” or examples/example_config.yaml for a runnable demo.")
            self._set_results("\n".join(lines))
            return

        self._populate_controls_from_cfg()
        self._set_tuning_state(True)
        self._set_results(f"Loaded: {path.name}\n\nAdjust sliders if needed, then click Run sizing.")
        self.root.after_idle(self._sync_all_scales)

    def _populate_controls_from_cfg(self) -> None:
        assert self.base_cfg is not None
        cfg = self.base_cfg
        for ui_id, keys in UI_CONTROL_TO_CFG_KEYS.items():
            val = require_param(cfg, *keys)
            if ui_id == "n_packs":
                self.controls[ui_id].set(int(val))
                if ui_id in self._scales:
                    self._scales[ui_id].set(int(val))
            else:
                fv = float(val)
                self.controls[ui_id].set(fv)
                if ui_id in self._scales:
                    self._scales[ui_id].set(fv)
            self._refresh_owner_caption(ui_id)
        t_box = float(self.controls["box_target_temperature_k"].get())
        t_rad = float(self.controls["radiator_temperature_k"].get())
        if t_rad > t_box:
            self.controls["radiator_temperature_k"].set(t_box)

    def _sync_all_scales(self) -> None:
        for ui_id, scale in self._scales.items():
            var = self.controls[ui_id]
            if ui_id == "n_packs":
                scale.set(int(var.get()))
            else:
                scale.set(float(var.get()))

    def run_sizing(self) -> None:
        blocked, messages = app_gate_blocked(self.base_cfg or {})
        if blocked:
            self._set_results("Blocked:\n" + "\n".join(f"  • {m}" for m in messages))
            return
        try:
            cfg, text, results, sens = run_sizing_report(self.base_cfg or {}, self.controls)
            self.last_working_cfg = cfg
            self.last_results = results
            self.last_sens = sens
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
            cfg = build_working_cfg(self.base_cfg, self.controls)
            write_sizing_pdf(Path(path), cfg, self.last_results, self.last_sens)
            messagebox.showinfo("Save PDF", f"Wrote {path}")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))


def main() -> None:
    if tk is None:
        print("Tkinter is not installed.", file=sys.stderr)
        print("On Linux try: sudo apt install python3-tk", file=sys.stderr)
        sys.exit(1)
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