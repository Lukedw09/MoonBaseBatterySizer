#!/usr/bin/env python3
"""Tkinter desktop UI for Moon Base pack + radiator sizer."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from gui_logic import (
    EXAMPLE_CFG,
    UI_CONTROL_TO_CFG_KEYS,
    app_gate_blocked,
    default_config_path,
    effective_owner_label,
    leaf_owner,
    load_config,
    param_value,
    run_sizing_report,
    write_sizing_pdf,
)
from sizer import DesignInputError

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - headless CI may lack tkinter
    tk = None  # type: ignore[misc, assignment]
    filedialog = messagebox = ttk = None  # type: ignore[misc, assignment]

# Left tuning column: label (28 chars) + Scale trough + owner caption — must fit inside paned min width.
TUNING_PANEL_MIN_WIDTH = 560
SCALE_LENGTH = 190

GUI_FIELD_LABELS: Dict[str, str] = {
    "n_packs": "n_packs",
    "primary_w": "Night load (W)",
    "t_dark_h": "Night hours",
    "specific_energy_wh_per_kg_low": "Specific energy low (Wh/kg)",
    "specific_energy_wh_per_kg_high": "Specific energy high (Wh/kg)",
    "pack_volumetric_energy_density_wh_per_m3": "Pack volumetric density (Wh/m³)",
    "depth_of_discharge": "Depth of discharge",
    "efficiency": "Discharge η",
    "packaging_insulation_mass_factor": "Packaging factor",
    "box_target_temperature_k": "T_box (K)",
    "radiator_temperature_k": "T_rad (K)",
    "radiator_emissivity": "Radiator ε",
    "warm_up_h": "Warm-up h",
    "panel_efficiency": "Panel η",
    "sun_incidence_cosine": "cos(incidence)",
}


def _horizontal_scale(
    parent: tk.Misc,
    var: tk.Variable,
    *,
    from_: float,
    to: float,
    resolution: float,
    length: int = SCALE_LENGTH,
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
        self.base_cfg: Optional[dict] = None
        self.loaded_path: Optional[Path] = None
        self.last_results = None
        self.last_sens = None
        self.last_working_cfg: Optional[dict] = None
        self.controls: Dict[str, tk.Variable] = {}
        self._scales: Dict[str, tk.Scale] = {}
        self._field_labels: Dict[str, tk.Widget] = {}
        self._input_widgets: Dict[str, tk.Widget] = {}
        self._unset_placeholders: Dict[str, tk.Widget] = {}
        self._owner_labels: Dict[str, tk.Label] = {}
        self._scale_ui_ids = frozenset(
            {"depth_of_discharge", "efficiency", "panel_efficiency", "sun_incidence_cosine"}
        )
        self._tuning_widgets: List[tk.Widget] = []
        self._results_fresh = False

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
        self._tuning_pane = left_outer
        paned.add(left_outer, weight=0)
        canvas = tk.Canvas(left_outer, highlightthickness=0)
        scroll = ttk.Scrollbar(left_outer, orient=tk.VERTICAL, command=canvas.yview)
        self.tuning_frame = ttk.Frame(canvas, padding=4)
        self._tuning_canvas = canvas

        def _on_tuning_frame_configure(_event: tk.Event) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_tuning_canvas_configure(event: tk.Event) -> None:
            canvas.itemconfigure(self._tuning_canvas_window, width=max(event.width, 1))

        self.tuning_frame.bind("<Configure>", _on_tuning_frame_configure)
        self._tuning_canvas_window = canvas.create_window(
            (0, 0), window=self.tuning_frame, anchor="nw", width=TUNING_PANEL_MIN_WIDTH
        )
        canvas.bind("<Configure>", _on_tuning_canvas_configure)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._paned = paned

        right = ttk.Frame(paned, padding=4)
        paned.add(right, weight=2)
        ttk.Label(right, text="Results").pack(anchor=tk.W)
        text_wrap = ttk.Frame(right)
        text_wrap.pack(fill=tk.BOTH, expand=True)
        self.results_text = tk.Text(text_wrap, wrap=tk.WORD, state=tk.DISABLED, font=("Courier", 9))
        yscroll = ttk.Scrollbar(text_wrap, orient=tk.VERTICAL, command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=yscroll.set)
        self.results_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
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
        self.root.after_idle(self._fit_window_to_content)

    def _fit_window_to_content(self) -> None:
        self.root.update_idletasks()
        try:
            self._paned.sashpos(0, TUNING_PANEL_MIN_WIDTH)
        except tk.TclError:
            pass
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        margin_w, margin_h = 12, 12
        w = max(req_w + margin_w, TUNING_PANEL_MIN_WIDTH + 440)
        scroll_h = 0
        bbox = self._tuning_canvas.bbox("all")
        if bbox:
            scroll_h = int(bbox[3] - bbox[1]) + self._tuning_canvas.winfo_rooty() - self.root.winfo_rooty() + 48
        h = max(req_h + margin_h, scroll_h, 560)
        self.root.minsize(w, h)
        self.root.geometry(f"{w}x{h}")
        self.root.update_idletasks()

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
        row.pack(fill=tk.X, pady=2, anchor=tk.W)
        input_row = ttk.Frame(row)
        input_row.pack(fill=tk.X, anchor=tk.W)
        field_lbl = ttk.Label(input_row, text=label, width=28, anchor=tk.W)
        field_lbl.pack(side=tk.LEFT, anchor=tk.NW)
        self._field_labels[ui_id] = field_lbl
        widget = build(input_row, var)
        is_scale = isinstance(widget, tk.Scale)
        self._input_widgets[ui_id] = widget
        unset_ph = ttk.Label(input_row, text="unset", width=14, anchor=tk.W)
        self._unset_placeholders[ui_id] = unset_ph
        if is_scale:
            widget.pack(side=tk.LEFT, fill=tk.NONE, expand=False)
            self._scales[ui_id] = widget
            widget.pack_forget()
            unset_ph.pack(side=tk.LEFT, padx=4)
        else:
            widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
            unset_ph.pack_forget()
        own = ttk.Label(
            row,
            text="",
            font=("TkDefaultFont", 8),
            foreground="gray",
            wraplength=TUNING_PANEL_MIN_WIDTH - 12,
            justify=tk.LEFT,
        )
        own.pack(fill=tk.X, anchor=tk.W, pady=(2, 0), padx=(0, 4))
        self._owner_labels[ui_id] = own
        self.controls[ui_id] = var
        self._tuning_widgets.extend([row, input_row, widget, own, unset_ph])
        var.trace_add(
            "write",
            lambda *_args, uid=ui_id: (self._refresh_owner_caption(uid), self._invalidate_saved_results()),
        )

    def _show_control_unset(self, ui_id: str) -> None:
        widget = self._input_widgets[ui_id]
        placeholder = self._unset_placeholders[ui_id]
        if ui_id in self._scale_ui_ids:
            widget.pack_forget()
            placeholder.pack(side=tk.LEFT, padx=4)
        else:
            var = self.controls[ui_id]
            var.set("unset")

    def _show_control_value(self, ui_id: str, val: Any) -> None:
        widget = self._input_widgets[ui_id]
        placeholder = self._unset_placeholders[ui_id]
        placeholder.pack_forget()
        if ui_id in self._scale_ui_ids:
            fv = float(val)
            self.controls[ui_id].set(fv)
            widget.pack(side=tk.LEFT, fill=tk.NONE, expand=False)
            if ui_id in self._scales:
                self._scales[ui_id].set(fv)
        elif ui_id == "n_packs":
            self.controls[ui_id].set(str(int(val)))
        else:
            self.controls[ui_id].set(str(float(val)))

    def _build_tuning_controls(self) -> None:
        ttk.Label(
            self.tuning_frame,
            text="Tuning (ui-override only when changed)",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        def scale(row: ttk.Frame, var: tk.Variable, from_, to, resolution=1.0) -> tk.Widget:
            return _horizontal_scale(row, var, from_=from_, to=to, resolution=resolution)

        root = self.root

        def spin(r: ttk.Frame, v: tk.Variable, **kw) -> tk.Widget:
            return ttk.Spinbox(r, textvariable=v, width=12, **kw)

        self._add_control(
            "n_packs",
            "n_packs",
            tk.StringVar(master=root, value="unset"),
            build=lambda r, v: spin(r, v, from_=1, to=512),
        )
        self._add_control(
            "primary_w",
            "Night load (W)",
            tk.StringVar(master=root, value="unset"),
            build=lambda r, v: spin(r, v, from_=0, to=20000),
        )
        self._add_control(
            "t_dark_h",
            "Night hours",
            tk.StringVar(master=root, value="unset"),
            build=lambda r, v: spin(r, v, from_=1, to=240, increment=0.5),
        )
        self._add_control(
            "specific_energy_wh_per_kg_low",
            "Specific energy low (Wh/kg)",
            tk.StringVar(master=root, value="unset"),
            build=lambda r, v: spin(r, v, from_=50, to=400),
        )
        self._add_control(
            "specific_energy_wh_per_kg_high",
            "Specific energy high (Wh/kg)",
            tk.StringVar(master=root, value="unset"),
            build=lambda r, v: spin(r, v, from_=50, to=400),
        )
        self._add_control(
            "pack_volumetric_energy_density_wh_per_m3",
            "Pack volumetric density (Wh/m³)",
            tk.StringVar(master=root, value="unset"),
            build=lambda r, v: spin(r, v, from_=50000, to=500000, increment=1000),
        )
        self._add_control(
            "depth_of_discharge",
            "Depth of discharge",
            tk.DoubleVar(master=root),
            build=lambda r, v: scale(r, v, 0.05, 1.0, 0.01),
        )
        self._add_control(
            "efficiency",
            "Discharge η",
            tk.DoubleVar(master=root),
            build=lambda r, v: scale(r, v, 0.05, 1.0, 0.01),
        )
        self._add_control(
            "packaging_insulation_mass_factor",
            "Packaging factor",
            tk.StringVar(master=root, value="unset"),
            build=lambda r, v: spin(r, v, from_=0.5, to=3.0, increment=0.05),
        )
        self._add_control(
            "box_target_temperature_k",
            "T_box (K)",
            tk.StringVar(master=root, value="unset"),
            build=lambda r, v: spin(r, v, from_=200, to=310, increment=0.5),
        )
        self._add_control(
            "radiator_temperature_k",
            "T_rad (K)",
            tk.StringVar(master=root, value="unset"),
            build=lambda r, v: spin(r, v, from_=200, to=310, increment=0.5),
        )
        self._add_control(
            "radiator_emissivity",
            "Radiator ε",
            tk.StringVar(master=root, value="unset"),
            build=lambda r, v: spin(r, v, from_=0.05, to=1.0, increment=0.01),
        )
        self._add_control(
            "warm_up_h",
            "Warm-up h",
            tk.StringVar(master=root, value="unset"),
            build=lambda r, v: spin(r, v, from_=0.5, to=24, increment=0.25),
        )
        self._add_control(
            "panel_efficiency",
            "Panel η",
            tk.DoubleVar(master=root),
            build=lambda r, v: scale(r, v, 0.05, 0.45, 0.01),
        )
        self._add_control(
            "sun_incidence_cosine",
            "cos(incidence)",
            tk.DoubleVar(master=root),
            build=lambda r, v: scale(r, v, 0.05, 1.0, 0.01),
        )

    def _refresh_owner_caption(self, ui_id: str) -> None:
        if not self.base_cfg:
            return
        keys = UI_CONTROL_TO_CFG_KEYS[ui_id]
        var = self.controls[ui_id]
        base_val = param_value(self.base_cfg, *keys)
        prior = leaf_owner(self.base_cfg, *keys) or "TODO-luke"
        if base_val is None:
            self._owner_labels[ui_id].configure(text=f"owner: {prior} (unset)")
            return
        try:
            raw = var.get()
            if ui_id == "n_packs":
                cur = int(str(raw).strip())
            elif ui_id in self._scale_ui_ids:
                cur = float(raw)
            else:
                cur = float(str(raw).strip())
        except (tk.TclError, TypeError, ValueError):
            return
        self._owner_labels[ui_id].configure(
            text=f"owner: {effective_owner_label(self.base_cfg, *keys, current_value=cur)}"
        )

    def _invalidate_saved_results(self) -> None:
        if self._results_fresh:
            self._results_fresh = False
            self.pdf_btn.configure(state=tk.DISABLED)

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
        if not enabled:
            self.pdf_btn.configure(state=tk.DISABLED)

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
        self._results_fresh = False
        self.last_results = None
        self.last_sens = None
        self.last_working_cfg = None
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
        self._populate_controls_from_cfg(allow_partial=blocked)
        if blocked:
            self._set_tuning_state(False)
            lines = [f"Loaded: {path.name}", "", "Design incomplete — fix these before tuning or run:\n"]
            lines.extend(f"  • {m}" for m in messages)
            lines.append("\nUse “Load EXAMPLE config…” or examples/example_config.yaml for a runnable demo.")
            self._set_results("\n".join(lines))
            self.root.after_idle(self._sync_all_scales)
            self.root.after_idle(self._fit_window_to_content)
            return

        self._set_tuning_state(True)
        self._set_results(f"Loaded: {path.name}\n\nAdjust sliders if needed, then click Run sizing.")
        self.root.after_idle(self._sync_all_scales)
        self.root.after_idle(self._fit_window_to_content)

    def _populate_controls_from_cfg(self, *, allow_partial: bool) -> None:
        assert self.base_cfg is not None
        cfg = self.base_cfg
        for ui_id in UI_CONTROL_TO_CFG_KEYS:
            self._show_control_unset(ui_id)
        for ui_id, keys in UI_CONTROL_TO_CFG_KEYS.items():
            val = param_value(cfg, *keys)
            if val is None:
                self._refresh_owner_caption(ui_id)
                if not allow_partial:
                    raise DesignInputError([f"{'.'.join(keys)}"])
                continue
            self._show_control_value(ui_id, val)
            self._refresh_owner_caption(ui_id)

    def _sync_all_scales(self) -> None:
        for ui_id, scale in self._scales.items():
            val = param_value(self.base_cfg or {}, *UI_CONTROL_TO_CFG_KEYS[ui_id])
            if val is None:
                continue
            scale.set(float(val))

    def run_sizing(self) -> None:
        blocked, messages = app_gate_blocked(self.base_cfg or {})
        if blocked:
            self._set_results("Blocked:\n" + "\n".join(f"  • {m}" for m in messages))
            return
        try:
            cfg, text, results, sens = run_sizing_report(self.base_cfg or {}, self.controls)
            self.last_working_cfg = copy.deepcopy(cfg)
            self.last_results = results
            self.last_sens = sens
            self._set_results(text)
            self._results_fresh = True
            self.pdf_btn.configure(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("Run failed", str(e))

    def save_pdf(self) -> None:
        if (
            not self._results_fresh
            or self.last_working_cfg is None
            or self.last_results is None
            or self.last_sens is None
        ):
            messagebox.showinfo("Save PDF", "Run sizing first (controls must match the last run).")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile="moon_base_sizer_report.pdf",
        )
        if not path:
            return
        try:
            write_sizing_pdf(Path(path), self.last_working_cfg, self.last_results, self.last_sens)
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