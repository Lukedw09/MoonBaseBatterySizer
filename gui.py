#!/usr/bin/env python3
"""Tkinter desktop UI for Moon Base pack + radiator sizer."""

from __future__ import annotations

import copy
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from gui_logic import (
    EXAMPLE_CFG,
    UI_CONTROL_TO_CFG_KEYS,
    app_gate_blocked,
    default_config_path,
    effective_owner_label,
    leaf_owner,
    load_config,
    param_value,
    UiInputError,
    parse_ui_control_value,
    run_sizing_report,
    write_sizing_pdf,
)
from sizer import ConfigError, DesignInputError, layout_unused_input_messages

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - headless CI may lack tkinter
    tk = None  # type: ignore[misc, assignment]
    filedialog = messagebox = ttk = None  # type: ignore[misc, assignment]

TUNING_PANEL_MIN_WIDTH = 520
SCALE_LENGTH = 190
AUTO_SIZING_DEBOUNCE_MS = 600
SCALE_KEY_DEBOUNCE_MS = 300
ACCENT_COLOR = "#0d9488"
HEADER_BG = "#0f172a"
HEADER_FG = "#f8fafc"
CONTENT_BG = "#f8fafc"
PANE_RIGHT_MIN_WIDTH = 360

METRIC_TILE_KEYS: Tuple[str, ...] = (
    "Pack mass",
    "System mass",
    "Q_internal",
    "Excess heat",
    "ΔT coast",
    "Min temp margin",
)

_WHEEL_SCROLL_SEQS = ("<MouseWheel>", "<Button-4>", "<Button-5>")

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

CONTROL_SECTIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Geometry", ("n_packs", "primary_w", "t_dark_h")),
    (
        "Battery",
        (
            "specific_energy_wh_per_kg_low",
            "specific_energy_wh_per_kg_high",
            "pack_volumetric_energy_density_wh_per_m3",
            "depth_of_discharge",
            "efficiency",
            "packaging_insulation_mass_factor",
        ),
    ),
    ("Thermal", ("box_target_temperature_k",)),
    ("Radiator", ("radiator_temperature_k", "radiator_emissivity")),
    ("Wake panel", ("warm_up_h", "panel_efficiency", "sun_incidence_cosine")),
)


def program_config_path() -> Path:
    """config.yaml beside this program (Luke's file when present)."""
    return default_config_path()


class _SnapshotControls(Mapping[str, Any]):
    def __init__(self, values: Dict[str, Any]) -> None:
        self._values = values

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self):
        return iter(self._values)


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


def _apply_theme(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=CONTENT_BG)
    style.configure("TFrame", background=CONTENT_BG)
    style.configure("App.TFrame", background=CONTENT_BG)
    style.configure("TLabel", background=CONTENT_BG, foreground="#0f172a")
    style.configure("TLabelframe", background=CONTENT_BG, bordercolor="#cbd5e1")
    style.configure("TLabelframe.Label", background=CONTENT_BG, foreground=ACCENT_COLOR, font=("Segoe UI", 10, "bold"))
    style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"), foreground="#0f172a", background=CONTENT_BG)
    style.configure("Section.TLabelframe", padding=12)
    style.configure("Section.TLabelframe.Label", font=("Segoe UI", 10, "bold"), foreground=ACCENT_COLOR)
    style.configure("Results.TLabelframe", padding=10)
    style.configure("Status.TLabel", font=("Segoe UI", 9), foreground="#475569")
    style.configure("StatusBar.TFrame", background="#e2e8f0")
    style.configure("Update.TLabel", font=("Segoe UI", 10, "bold"), foreground="#b45309", background=CONTENT_BG)
    style.configure("TButton", padding=(12, 6), font=("Segoe UI", 9))
    style.configure(
        "Accent.TButton",
        padding=(12, 6),
        font=("Segoe UI", 9, "bold"),
        background="#0f766e",
        foreground=HEADER_FG,
    )
    style.map("Accent.TButton", background=[("active", ACCENT_COLOR), ("!disabled", "#0f766e")])
    style.configure("MetricCaption.TLabel", font=("Segoe UI", 9), foreground="#64748b")
    style.configure("MetricValue.TLabel", font=("Segoe UI", 15, "bold"), foreground=ACCENT_COLOR)
    style.configure("MetricWarn.TLabel", font=("Segoe UI", 15, "bold"), foreground="#dc2626")
    style.configure("MetricAmber.TLabel", font=("Segoe UI", 15, "bold"), foreground="#d97706")
    style.configure("MetricCase.TLabel", font=("Segoe UI", 8), foreground="#64748b")
    style.configure("MetricTile.TFrame", relief="solid", borderwidth=1)
    root.configure(bg=CONTENT_BG)
    return style


def _case_tile_label(result: Any) -> str:
    name = getattr(result, "load_name", "case")
    se = getattr(result, "specific_energy_wh_kg", 0.0)
    return f"{name} @ {float(se):.0f} Wh/kg"


def _margin_case_subtitle(result: Any, *, stuck_open: bool) -> str:
    base = _case_tile_label(result)
    if stuck_open:
        return f"{base} — Louvers-stuck-open cold coast"
    return f"{base} — LiPo margin at dawn (louvers closed)"


def _details_monospace_font(root: tk.Misc) -> Tuple[str, int]:
    if sys.platform.startswith("win"):
        return ("Consolas", 9)
    try:
        import tkinter.font as tkfont

        fixed = tkfont.nametofont("TkFixedFont")
        return (str(fixed.actual("family")), 9)
    except tk.TclError:
        return ("Courier", 9)


def metrics_from_case_results(
    results: List[Any], cfg: Optional[dict] = None
) -> Dict[str, Tuple[str, str, str]]:
    """Tile caption -> (value, case subtitle, tone: normal|warn|amber)."""
    if not results:
        return {k: ("—", "", "normal") for k in METRIC_TILE_KEYS}
    primary = next(
        (r for r in results if getattr(r, "case", None) == "primary" and getattr(r, "specific_energy_wh_kg", 0) == 150),
        None,
    )
    if primary is None:
        primary = next((r for r in results if getattr(r, "case", None) == "primary"), results[0])
    plbl = _case_tile_label(primary)
    pack = getattr(primary.battery, "mass_kg", None)
    sys_m = getattr(primary, "system_mass_kg", None)
    dt = getattr(primary, "transient_delta_t_k", None)
    out: Dict[str, Tuple[str, str, str]] = {
        "Pack mass": (f"{pack:.1f} kg" if pack is not None else "—", plbl, "normal"),
        "System mass": (f"{sys_m:.1f} kg" if sys_m is not None else "—", plbl, "normal"),
        "Q_internal": (f"{primary.q_internal_w:.1f} W", plbl, "normal"),
        "Excess heat": (f"{primary.q_excess_w:.1f} W", plbl, "normal"),
        "ΔT coast": (f"{dt:.2f} K" if dt is not None else "—", plbl, "normal"),
    }
    margin_thr: Optional[float] = None
    if cfg is not None:
        thr = param_value(cfg, "battery", "lipo_margin_threshold_k")
        if thr is not None:
            margin_thr = float(thr)
    min_margin: Optional[float] = None
    min_lbl = ""
    min_stuck = False
    for r in results:
        closed = getattr(r, "coast_margin_lipo_k", None)
        stuck = getattr(r, "coast_stuck_open_margin_lipo_k", None)
        for val, is_stuck in ((closed, False), (stuck, True)):
            if val is None:
                continue
            fv = float(val)
            if min_margin is None or fv < min_margin:
                min_margin = fv
                min_stuck = is_stuck
                min_lbl = _margin_case_subtitle(r, stuck_open=is_stuck)
    if min_margin is not None:
        if min_margin < 0:
            tone = "warn"
        elif margin_thr is not None and min_margin < margin_thr:
            tone = "amber"
        else:
            tone = "normal"
        out["Min temp margin"] = (f"{min_margin:.2f} K", min_lbl, tone)
    else:
        out["Min temp margin"] = ("—", "", "normal")
    return out


def _sizing_worker(
    run_id: int,
    base_cfg: dict,
    snapshot: Dict[str, Any],
    out_queue: "queue.Queue[Tuple[int, Tuple[str, Any]]]",
) -> None:
    try:
        cfg, text, results, sens = run_sizing_report(base_cfg, _SnapshotControls(snapshot))
        payload: Tuple[str, Any] = ("ok", (cfg, text, results, sens, snapshot))
    except Exception as e:
        payload = ("err", e)
    out_queue.put((run_id, payload))


class SizerGUI:
    def __init__(
        self, root: tk.Tk, *, config_path: Optional[Path] = None, auto_run_after_load: bool = True
    ) -> None:
        self.root = root
        self.root.title("Moon Base Battery Sizer")
        self.root.minsize(1100, 640)
        _apply_theme(root)

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
        self._controls_editable = True
        self._input_invalid = False
        self._populating_cfg = False
        self._sizing_active = False
        self._sizing_pending = False
        self._sizing_inflight = 0
        self._sizing_generation = 0
        self._debounce_after_id: Optional[str] = None
        self._poll_after_id: Optional[str] = None
        self._last_valid_results_text: Optional[str] = None
        self._sizing_queue: queue.Queue[Tuple[int, Tuple[str, Any]]] = queue.Queue()
        self._auto_run_after_load = auto_run_after_load
        self._metric_vars: Dict[str, tk.StringVar] = {}
        self._metric_case_vars: Dict[str, tk.StringVar] = {}
        self._metric_value_labels: Dict[str, ttk.Label] = {}
        self._last_display_generation = 0
        self._pane_heading_label: Optional[ttk.Label] = None
        self._wheel_redirect_tag = "MoonBaseWheelToCanvas"
        self._worker_threads: List[threading.Thread] = []
        self._shutting_down = False
        self._scale_debounce_after_id: Optional[str] = None

        header = tk.Frame(root, bg=HEADER_BG, height=72)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header,
            text="Moon Base Battery Sizer",
            bg=HEADER_BG,
            fg=HEADER_FG,
            font=("Segoe UI", 16, "bold"),
        ).pack(side=tk.LEFT, padx=(18, 24), pady=18)
        cfg_row = tk.Frame(header, bg=HEADER_BG)
        cfg_row.pack(side=tk.RIGHT, padx=14, pady=12)
        tk.Label(cfg_row, text="Config:", bg=HEADER_BG, fg="#94a3b8", font=("Segoe UI", 10)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self.config_name_label = tk.Label(
            cfg_row, text="—", bg=HEADER_BG, fg=HEADER_FG, font=("Segoe UI", 10, "bold")
        )
        self.config_name_label.pack(side=tk.LEFT, padx=(0, 14))
        ttk.Button(cfg_row, text="Browse…", command=self._browse_config, style="Accent.TButton").pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(cfg_row, text="Open example…", command=self._load_example_config).pack(side=tk.LEFT, padx=4)

        body = ttk.Frame(root, padding=(10, 8, 10, 6))
        body.pack(fill=tk.BOTH, expand=True)
        self._body = body

        paned = ttk.Panedwindow(body, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        self._paned = paned

        left_outer = ttk.Frame(paned, style="App.TFrame", width=TUNING_PANEL_MIN_WIDTH)
        self._tuning_pane = left_outer
        paned.add(left_outer, weight=1)

        self._tuning_canvas = tk.Canvas(
            left_outer, highlightthickness=0, borderwidth=0, bg="#ffffff", width=TUNING_PANEL_MIN_WIDTH - 20
        )
        scroll = ttk.Scrollbar(left_outer, orient=tk.VERTICAL, command=self._tuning_canvas.yview)
        self.tuning_frame = ttk.Frame(self._tuning_canvas, padding=4)
        self._tuning_canvas_window = self._tuning_canvas.create_window(
            (0, 0), window=self.tuning_frame, anchor="nw", width=TUNING_PANEL_MIN_WIDTH
        )

        def _on_tuning_frame_configure(_event: tk.Event) -> None:
            self._tuning_canvas.configure(scrollregion=self._tuning_canvas.bbox("all"))

        def _on_tuning_canvas_configure(event: tk.Event) -> None:
            self._tuning_canvas.itemconfigure(self._tuning_canvas_window, width=max(event.width, 1))

        self.tuning_frame.bind("<Configure>", _on_tuning_frame_configure)
        self._tuning_canvas.bind("<Configure>", _on_tuning_canvas_configure)
        self._tuning_canvas.configure(yscrollcommand=scroll.set)
        self._tuning_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_tuning_mousewheel(self._tuning_canvas)
        self._bind_tuning_mousewheel(self.tuning_frame)

        self._right_pane = ttk.Frame(paned, padding=(0, 0, 0, 0))
        paned.add(self._right_pane, weight=3)

        right = ttk.Frame(self._right_pane, padding=4)
        right.pack(fill=tk.BOTH, expand=True)

        results_card = ttk.Labelframe(right, text="Results", style="Results.TLabelframe")
        results_card.pack(fill=tk.BOTH, expand=True)
        self.update_banner = ttk.Label(results_card, text="", style="Update.TLabel")
        self.update_banner.pack(anchor=tk.W, pady=(0, 2))

        self._metrics_frame = ttk.Frame(results_card)
        self._metrics_frame.pack(fill=tk.X, pady=(0, 6))
        for idx, caption in enumerate(METRIC_TILE_KEYS):
            var = tk.StringVar(value="—")
            case_var = tk.StringVar(value="")
            self._metric_vars[caption] = var
            self._metric_case_vars[caption] = case_var
            tile = ttk.Frame(self._metrics_frame, style="MetricTile.TFrame", padding=8)
            tile.grid(row=idx // 3, column=idx % 3, sticky="nsew", padx=4, pady=4)
            ttk.Label(tile, text=caption, style="MetricCaption.TLabel").pack(anchor=tk.W)
            val_lbl = ttk.Label(tile, textvariable=var, style="MetricValue.TLabel")
            val_lbl.pack(anchor=tk.W)
            self._metric_value_labels[caption] = val_lbl
            ttk.Label(tile, textvariable=case_var, style="MetricCase.TLabel", wraplength=200).pack(anchor=tk.W)
        for col in range(3):
            self._metrics_frame.columnconfigure(col, weight=1, uniform="metrics")

        details_card = ttk.Labelframe(results_card, text="Details", style="Section.TLabelframe", padding=4)
        details_card.pack(fill=tk.BOTH, expand=True)
        text_wrap = ttk.Frame(details_card)
        text_wrap.pack(fill=tk.BOTH, expand=True)
        self.results_text = tk.Text(
            text_wrap,
            wrap=tk.NONE,
            state=tk.DISABLED,
            font=_details_monospace_font(root),
            relief=tk.FLAT,
            borderwidth=0,
            padx=6,
            pady=6,
            bg="#ffffff",
            fg="#0f172a",
            height=14,
        )
        yscroll = ttk.Scrollbar(text_wrap, orient=tk.VERTICAL, command=self.results_text.yview)
        xscroll = ttk.Scrollbar(text_wrap, orient=tk.HORIZONTAL, command=self.results_text.xview)
        self.results_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.results_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        text_wrap.rowconfigure(0, weight=1)
        text_wrap.columnconfigure(0, weight=1)

        btn_row = ttk.Frame(right)
        btn_row.pack(fill=tk.X, pady=(8, 0))
        self.run_btn = ttk.Button(btn_row, text="Run sizing", style="Accent.TButton", command=self.run_sizing)
        self.run_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.pdf_btn = ttk.Button(btn_row, text="Save PDF", command=self.save_pdf, state=tk.DISABLED)
        self.pdf_btn.pack(side=tk.LEFT, padx=4)

        status = ttk.Frame(root, style="StatusBar.TFrame", padding=(12, 6))
        status.pack(fill=tk.X)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel", anchor=tk.W).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        for seq in _WHEEL_SCROLL_SEQS:
            root.bind_class(self._wheel_redirect_tag, seq, self._wheel_redirect_to_canvas)

        self._readonly_scale_tag = "MoonBaseReadonlyScale"
        for seq in (
            "<Button-1>",
            "<Button-2>",
            "<Button-3>",
            "<Double-Button-1>",
            "<B1-Motion>",
            "<B2-Motion>",
            "<B3-Motion>",
            "<ButtonRelease-1>",
            "<ButtonRelease-2>",
            "<ButtonRelease-3>",
            "<Key>",
        ):
            root.bind_class(self._readonly_scale_tag, seq, lambda _e: "break")
        for seq in _WHEEL_SCROLL_SEQS:
            root.bind_class(self._readonly_scale_tag, seq, self._wheel_redirect_to_canvas)

        self._build_tuning_controls()
        start = config_path if config_path is not None else program_config_path()
        self._load_config_path(start)
        self.root.bind("<Map>", lambda _e: self._layout_panes(), add=True)
        self.root.after_idle(self._layout_panes)
        self.root.after_idle(self._fit_window_to_content)
        self.root.protocol("WM_DELETE_WINDOW", self._request_close)

    def _bind_tuning_mousewheel(self, widget: tk.Misc) -> None:
        widget.bind("<Enter>", self._tuning_wheel_bind_active, add=True)
        widget.bind("<Leave>", self._tuning_wheel_bind_inactive, add=True)

    def _tuning_wheel_bind_active(self, _event: tk.Event) -> None:
        self.root.bind_all("<MouseWheel>", self._on_tuning_wheel, add=True)
        self.root.bind_all("<Button-4>", self._on_tuning_wheel, add=True)
        self.root.bind_all("<Button-5>", self._on_tuning_wheel, add=True)

    def _tuning_wheel_bind_inactive(self, _event: tk.Event) -> None:
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")

    def _on_tuning_wheel(self, event: tk.Event) -> str:
        w = event.widget
        while w is not None:
            if isinstance(w, tk.Scale):
                return self._scale_wheel_scrolls_canvas(event)
            w = w.master
        if event.delta:
            delta = -1 if event.delta > 0 else 1
        elif event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            return "break"
        self._tuning_canvas.yview_scroll(delta, "units")
        return "break"

    def _wheel_redirect_to_canvas(self, event: tk.Event) -> str:
        return self._scale_wheel_scrolls_canvas(event)

    def _scale_wheel_scrolls_canvas(self, event: tk.Event) -> str:
        if event.delta:
            delta = -1 if event.delta > 0 else 1
        elif event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            return "break"
        self._tuning_canvas.yview_scroll(delta, "units")
        return "break"

    def _attach_wheel_redirect(self, widget: tk.Misc) -> None:
        tags = widget.bindtags()
        if self._wheel_redirect_tag not in tags:
            widget.bindtags((self._wheel_redirect_tag,) + tags)

    def _layout_panes(self) -> None:
        self.root.update_idletasks()
        try:
            self._paned.sashpos(0, TUNING_PANEL_MIN_WIDTH)
        except tk.TclError:
            pass
        try:
            cv_w = max(self._tuning_canvas.winfo_width(), TUNING_PANEL_MIN_WIDTH - 24)
            self._tuning_canvas.itemconfigure(self._tuning_canvas_window, width=cv_w)
        except tk.TclError:
            pass
        if self._pane_heading_label is not None:
            wrap = max(self._tuning_canvas.winfo_width() - 16, 280)
            self._pane_heading_label.configure(wraplength=wrap)

    def layout_panes_for_display(self) -> None:
        """Public hook for tests and screenshot capture."""
        self._layout_panes()

    def _fit_window_to_content(self) -> None:
        self.root.update_idletasks()
        self._layout_panes()
        w = max(TUNING_PANEL_MIN_WIDTH + PANE_RIGHT_MIN_WIDTH + 40, 1200)
        h = max(self.root.winfo_reqheight(), 640)
        self.root.minsize(w, 640)
        if self.root.winfo_width() < w or self.root.winfo_height() < h:
            self.root.geometry(f"{w}x{h}")

    def _browse_config(self) -> None:
        path = filedialog.askopenfilename(
            title="Open config YAML",
            filetypes=[("YAML config", "*.yaml *.yml"), ("YAML", "*.yaml"), ("YML", "*.yml")],
        )
        if path:
            self._load_config_path(Path(path))

    def _load_example_config(self) -> None:
        self._load_config_path(EXAMPLE_CFG)

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _section_parent(self, title: str) -> ttk.Frame:
        frame = ttk.Labelframe(self.tuning_frame, text=title, style="Section.TLabelframe")
        frame.pack(fill=tk.X, pady=(0, 10), anchor=tk.W)
        return frame

    def _add_control(
        self,
        parent: ttk.Frame,
        ui_id: str,
        label: str,
        var: tk.Variable,
        *,
        build: Callable[[ttk.Frame, tk.Variable], tk.Widget],
    ) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=3, anchor=tk.W)
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
            widget.bind("<ButtonRelease-1>", self._on_scale_release, add=True)
            widget.bind("<KeyRelease>", self._on_scale_key_release, add=True)
            for seq in _WHEEL_SCROLL_SEQS:
                widget.bind(seq, self._wheel_redirect_to_canvas, add=True)
        else:
            widget.pack(side=tk.LEFT, fill=tk.X, expand=True)
            unset_ph.pack_forget()
            self._attach_wheel_redirect(widget)
            widget.bind("<Return>", lambda _e, uid=ui_id: self._schedule_auto_sizing(0, uid), add=True)
            widget.bind("<FocusOut>", lambda _e, uid=ui_id: self._schedule_auto_sizing(0, uid), add=True)
        own = ttk.Label(
            row,
            text="",
            font=("Segoe UI", 8),
            foreground="gray",
            wraplength=TUNING_PANEL_MIN_WIDTH - 24,
            justify=tk.LEFT,
        )
        own.pack(fill=tk.X, anchor=tk.W, pady=(2, 0), padx=(0, 4))
        self._owner_labels[ui_id] = own
        self.controls[ui_id] = var
        self._tuning_widgets.extend([row, input_row, widget, own, unset_ph])
        var.trace_add("write", lambda *_args, uid=ui_id: self._on_control_changed(uid))

    def _on_control_changed(self, ui_id: str) -> None:
        if self._populating_cfg:
            return
        self._refresh_owner_caption(ui_id)
        self._mark_results_stale()
        self._update_run_button_state()
        if ui_id not in self._scale_ui_ids and ui_id != "n_packs":
            self._schedule_debounced_sizing()
        elif ui_id == "n_packs":
            self._schedule_debounced_sizing()

    def _on_scale_release(self, _event: tk.Event) -> None:
        if self._populating_cfg or not self._controls_editable:
            return
        self._schedule_auto_sizing(0)

    def _on_scale_key_release(self, event: tk.Event) -> None:
        if self._populating_cfg or not self._controls_editable:
            return
        if event.keysym in ("Left", "Right", "Up", "Down", "Prior", "Next", "Home", "End"):
            if self._scale_debounce_after_id is not None:
                self.root.after_cancel(self._scale_debounce_after_id)
            self._scale_debounce_after_id = self.root.after(
                SCALE_KEY_DEBOUNCE_MS, self._scale_key_debounced_sizing
            )

    def _scale_key_debounced_sizing(self) -> None:
        self._scale_debounce_after_id = None
        if self._populating_cfg or not self._controls_editable:
            return
        self._schedule_auto_sizing(0)

    def _controls_match_snapshot(self, snapshot: Mapping[str, Any]) -> bool:
        for uid, val in snapshot.items():
            if uid not in self.controls:
                continue
            if str(self.controls[uid].get()) != str(val):
                return False
        return True

    def _sync_sizing_active(self) -> None:
        self._sizing_active = (
            self._sizing_inflight > 0 or not self._sizing_queue.empty() or self._sizing_pending
        )

    def _schedule_queue_poll(self) -> None:
        if not (self._sizing_inflight > 0 or not self._sizing_queue.empty()):
            return
        try:
            if self._poll_after_id is not None:
                self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = self.root.after(25, self._poll_sizing_queue)
        except tk.TclError:
            self._poll_after_id = None

    def _schedule_debounced_sizing(self) -> None:
        if self._debounce_after_id is not None:
            self.root.after_cancel(self._debounce_after_id)
        self._debounce_after_id = self.root.after(
            AUTO_SIZING_DEBOUNCE_MS, lambda: self._schedule_auto_sizing(0)
        )

    def _schedule_auto_sizing(self, delay_ms: int = 0, _ui_id: Optional[str] = None) -> None:
        if self._populating_cfg or not self._controls_editable:
            return
        if self._input_invalid or self._any_control_invalid():
            return
        if app_gate_blocked(self.base_cfg or {})[0]:
            return
        self._sizing_pending = True
        self._update_pdf_button_state()
        self._set_status("Update scheduled…")
        if delay_ms <= 0:
            self._start_sizing_run()
        else:
            self.root.after(delay_ms, self._start_sizing_run)

    def _start_sizing_run(self) -> None:
        if self._debounce_after_id is not None:
            self.root.after_cancel(self._debounce_after_id)
            self._debounce_after_id = None
        if not self._controls_editable or self.base_cfg is None:
            self._sizing_pending = False
            return
        if self._input_invalid or self._any_control_invalid():
            self._sizing_pending = False
            self._update_pdf_button_state()
            return
        if app_gate_blocked(self.base_cfg)[0]:
            self._sizing_pending = False
            return

        self._sizing_generation += 1
        run_id = self._sizing_generation
        self._sizing_pending = False
        self._sizing_inflight += 1
        self._sizing_active = True
        self._update_pdf_button_state()
        self.update_banner.configure(text="Updating…")
        self._set_status("Updating sizing…")

        snapshot = {uid: self.controls[uid].get() for uid in self.controls}
        base_cfg = copy.deepcopy(self.base_cfg)

        worker = threading.Thread(
            target=_sizing_worker,
            args=(run_id, base_cfg, snapshot, self._sizing_queue),
            daemon=False,
            name=f"sizing-{run_id}",
        )
        self._worker_threads.append(worker)
        worker.start()
        self._schedule_queue_poll()
        self._poll_sizing_queue()

    def _prune_worker_threads(self) -> None:
        self._worker_threads[:] = [t for t in self._worker_threads if t.is_alive()]

    def _request_close(self, *_args: Any) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        try:
            self.root.withdraw()
        except tk.TclError:
            pass
        if self._debounce_after_id is not None:
            try:
                self.root.after_cancel(self._debounce_after_id)
            except tk.TclError:
                pass
            self._debounce_after_id = None
        if self._scale_debounce_after_id is not None:
            try:
                self.root.after_cancel(self._scale_debounce_after_id)
            except tk.TclError:
                pass
            self._scale_debounce_after_id = None
        if self._poll_after_id is not None:
            try:
                self.root.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
            self._poll_after_id = None
        self._sizing_generation += 1
        self._sizing_pending = False
        try:
            self.root.quit()
        except tk.TclError:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except (OSError, ValueError, SystemError):
            pass
        os._exit(0)

    def _poll_sizing_queue(self) -> None:
        self._poll_after_id = None
        while True:
            try:
                run_id, payload = self._sizing_queue.get_nowait()
            except queue.Empty:
                break
            self._finish_sizing_run(run_id, payload)
        self._sync_sizing_active()
        if not self._sizing_active and self._sizing_inflight == 0:
            if str(self.update_banner.cget("text")) == "Updating…":
                self.update_banner.configure(text="")
        self._prune_worker_threads()
        self._update_pdf_button_state()
        self._update_run_button_state()
        self._schedule_queue_poll()

    def _finish_sizing_run(self, run_id: int, payload: Tuple[str, Any]) -> None:
        self._sizing_inflight = max(0, self._sizing_inflight - 1)
        stale = run_id != self._sizing_generation
        if not stale:
            kind, data = payload
            if kind == "ok":
                if len(data) == 4:
                    cfg, text, results, sens = data
                    snapshot: Dict[str, Any] = {}
                else:
                    cfg, text, results, sens, snapshot = data
                self.last_working_cfg = copy.deepcopy(cfg)
                self.last_results = results
                self.last_sens = sens
                self._last_valid_results_text = text
                self._results_fresh = True
                self.update_banner.configure(text="")
                self._set_results_display(text, current=True)
                self._refresh_metric_tiles_from_results(results)
                self._last_display_generation = run_id
                if snapshot and not self._controls_match_snapshot(snapshot):
                    self._set_status("Inputs changed — updating…")
                    self._mark_results_stale()
                    self._schedule_auto_sizing(50)
                else:
                    self._set_status("Sizing up to date")
            else:
                err = data
                if isinstance(err, (UiInputError, ConfigError)):
                    self._set_status(f"Input error: {err}")
                    self.update_banner.configure(text="")
                    self._show_results_error(str(err))
                elif isinstance(err, DesignInputError):
                    self._set_status("Design incomplete")
                    self.update_banner.configure(text="")
                    self._show_results_error("Blocked:\n" + "\n".join(f"  • {m}" for m in err.missing))
                else:
                    self._set_status("Sizing failed")
                    self.update_banner.configure(text="")
                    messagebox.showerror("Run failed", str(err))
                    self._show_results_error(str(err))

    def _show_results_error(self, message: str) -> None:
        if self._last_valid_results_text:
            banner = f"(Last valid run — current inputs not applied)\n\n{message}\n\n"
            self._set_results_display(self._last_valid_results_text, current=False, prefix=banner)
            if self.last_results is not None:
                self._refresh_metric_tiles_from_results(self.last_results)
        else:
            self._set_results_display(message, current=False)
            self._clear_metric_tiles()

    def _refresh_metric_tiles_from_results(self, results: List[Any]) -> None:
        cfg = self.last_working_cfg or self.base_cfg
        tiles = metrics_from_case_results(results, cfg)
        for caption, (val, case_lbl, tone) in tiles.items():
            if caption not in self._metric_vars:
                continue
            self._metric_vars[caption].set(val)
            self._metric_case_vars[caption].set(case_lbl)
            style = {
                "warn": "MetricWarn.TLabel",
                "amber": "MetricAmber.TLabel",
            }.get(tone, "MetricValue.TLabel")
            self._metric_value_labels[caption].configure(style=style)

    def _clear_metric_tiles(self) -> None:
        for var in self._metric_vars.values():
            var.set("—")
        for var in self._metric_case_vars.values():
            var.set("")
        for caption, lbl in self._metric_value_labels.items():
            lbl.configure(style="MetricValue.TLabel")

    def _set_results_display(self, body: str, *, current: bool, prefix: str = "") -> None:
        text = prefix + body
        self.results_text.configure(state=tk.NORMAL)
        self.results_text.delete("1.0", tk.END)
        self.results_text.insert(tk.END, text)
        self.results_text.configure(state=tk.DISABLED)
        if not current and not prefix:
            self._clear_metric_tiles()

    def _apply_scale_readonly_tags(self, locked: bool) -> None:
        for scale in self._scales.values():
            tags = scale.bindtags()
            if locked:
                if self._readonly_scale_tag not in tags:
                    scale.bindtags((self._readonly_scale_tag,) + tags)
            else:
                scale.bindtags(tuple(t for t in tags if t != self._readonly_scale_tag))

    def _show_control_unset(self, ui_id: str) -> None:
        widget = self._input_widgets[ui_id]
        placeholder = self._unset_placeholders[ui_id]
        if ui_id in self._scale_ui_ids:
            widget.pack_forget()
            placeholder.pack(side=tk.LEFT, padx=4)
        else:
            self.controls[ui_id].set("unset")

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
        self._pane_heading_label = ttk.Label(
            self.tuning_frame,
            text="Parameters — sizing updates after slider release or typing pause",
            style="Header.TLabel",
            wraplength=TUNING_PANEL_MIN_WIDTH - 32,
        )
        self._pane_heading_label.pack(anchor=tk.W, pady=(0, 8))

        def scale(row: ttk.Frame, var: tk.Variable, from_, to, resolution=1.0) -> tk.Widget:
            return _horizontal_scale(row, var, from_=from_, to=to, resolution=resolution)

        root = self.root

        def spin(r: ttk.Frame, v: tk.Variable, **kw) -> tk.Widget:
            return ttk.Spinbox(r, textvariable=v, width=12, **kw)

        builders: Dict[str, Callable[[ttk.Frame, tk.Variable], tk.Widget]] = {
            "n_packs": lambda r, v: spin(r, v, from_=1, to=512),
            "primary_w": lambda r, v: spin(r, v, from_=0, to=20000),
            "t_dark_h": lambda r, v: spin(r, v, from_=1, to=240, increment=0.5),
            "specific_energy_wh_per_kg_low": lambda r, v: spin(r, v, from_=50, to=400),
            "specific_energy_wh_per_kg_high": lambda r, v: spin(r, v, from_=50, to=400),
            "pack_volumetric_energy_density_wh_per_m3": lambda r, v: spin(
                r, v, from_=50000, to=500000, increment=1000
            ),
            "depth_of_discharge": lambda r, v: scale(r, v, 0.05, 1.0, 0.01),
            "efficiency": lambda r, v: scale(r, v, 0.05, 1.0, 0.01),
            "packaging_insulation_mass_factor": lambda r, v: spin(r, v, from_=0.5, to=3.0, increment=0.05),
            "box_target_temperature_k": lambda r, v: spin(r, v, from_=200, to=310, increment=0.5),
            "radiator_temperature_k": lambda r, v: spin(r, v, from_=200, to=310, increment=0.5),
            "radiator_emissivity": lambda r, v: spin(r, v, from_=0.05, to=1.0, increment=0.01),
            "warm_up_h": lambda r, v: spin(r, v, from_=0.5, to=24, increment=0.25),
            "panel_efficiency": lambda r, v: scale(r, v, 0.05, 0.45, 0.01),
            "sun_incidence_cosine": lambda r, v: scale(r, v, 0.05, 1.0, 0.01),
        }

        for section_title, ui_ids in CONTROL_SECTIONS:
            section = self._section_parent(section_title)
            for ui_id in ui_ids:
                self._add_control(
                    section,
                    ui_id,
                    GUI_FIELD_LABELS[ui_id],
                    self._new_control_var(ui_id, root),
                    build=builders[ui_id],
                )

        legs = self._section_parent("Legs")
        ttk.Label(
            legs,
            text="Leg conductor geometry and thermal mesh use YAML fields only (not edited in this pane).",
            wraplength=TUNING_PANEL_MIN_WIDTH - 40,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

    def _new_control_var(self, ui_id: str, master: tk.Misc) -> tk.Variable:
        if ui_id in self._scale_ui_ids:
            return tk.DoubleVar(master=master)
        return tk.StringVar(master=master, value="unset")

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
            cur = parse_ui_control_value(ui_id, var)
        except (UiInputError, tk.TclError, TypeError, ValueError):
            self._owner_labels[ui_id].configure(text=f"owner: {prior} — invalid input")
            return
        self._owner_labels[ui_id].configure(
            text=f"owner: {effective_owner_label(self.base_cfg, *keys, current_value=cur)}"
        )

    def _any_control_invalid(self) -> bool:
        if not self.base_cfg:
            return True
        for ui_id in UI_CONTROL_TO_CFG_KEYS:
            if param_value(self.base_cfg, *UI_CONTROL_TO_CFG_KEYS[ui_id]) is None:
                continue
            try:
                parse_ui_control_value(ui_id, self.controls[ui_id])
            except (UiInputError, tk.TclError, TypeError, ValueError):
                return True
        return False

    def _update_run_button_state(self) -> None:
        self._input_invalid = self._any_control_invalid()
        if not self._controls_editable:
            self.run_btn.configure(state=tk.DISABLED)
            return
        gate_ok = not app_gate_blocked(self.base_cfg or {})[0]
        self.run_btn.configure(state=tk.NORMAL if gate_ok and not self._input_invalid else tk.DISABLED)

    def _mark_results_stale(self) -> None:
        if self._results_fresh:
            self._results_fresh = False
        self._update_pdf_button_state()

    def _waiting_for_current_sizing(self) -> bool:
        return self._sizing_pending or (
            self._sizing_inflight > 0 and self._last_display_generation != self._sizing_generation
        )

    def _update_pdf_button_state(self) -> None:
        if self._waiting_for_current_sizing():
            self.pdf_btn.configure(state=tk.DISABLED)
        elif self._results_fresh and self.last_working_cfg is not None:
            self.pdf_btn.configure(state=tk.NORMAL)
        else:
            self.pdf_btn.configure(state=tk.DISABLED)

    def _set_tuning_state(self, enabled: bool) -> None:
        self._controls_editable = enabled
        state = tk.NORMAL if enabled else tk.DISABLED
        for w in self._tuning_widgets:
            if isinstance(w, tk.Scale):
                continue
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        if enabled:
            self._update_run_button_state()
        else:
            self.run_btn.configure(state=tk.DISABLED)
            self.pdf_btn.configure(state=tk.DISABLED)
        self._apply_scale_readonly_tags(not enabled)

    def _load_config_path(self, path: Path) -> None:
        self._cancel_pending_sizing()
        self.pdf_btn.configure(state=tk.DISABLED)
        self._results_fresh = False
        self.last_results = None
        self.last_sens = None
        self.last_working_cfg = None
        self._last_valid_results_text = None
        try:
            self.base_cfg = load_config(path)
            self.loaded_path = path
            self.config_name_label.configure(text=path.name)
        except Exception as e:
            self.base_cfg = None
            self.loaded_path = None
            self.config_name_label.configure(text="—")
            self._set_tuning_state(False)
            self._set_results_display(f"Could not load config:\n{e}", current=False)
            self._clear_metric_tiles()
            self._set_status("Failed to load config")
            return

        blocked, messages = app_gate_blocked(self.base_cfg)
        self._populating_cfg = True
        try:
            self._populate_controls_from_cfg(allow_partial=blocked)
        finally:
            self._populating_cfg = False
        layout_notes = layout_unused_input_messages(self.base_cfg)
        if blocked:
            self._set_tuning_state(False)
            lines = [f"Loaded: {path.name}", "", "Design incomplete — fix these before tuning or run:\n"]
            lines.extend(f"  • {m}" for m in messages)
            if layout_notes:
                lines.append("\nLayout (not used by current model):\n")
                lines.extend(f"  • {m}" for m in layout_notes)
            lines.append("\nUse Open example… or Browse… for a runnable demo.")
            self._set_results_display("\n".join(lines), current=False)
            self._clear_metric_tiles()
            self._set_status(f"Blocked — {path.name}")
            self.root.after_idle(self._sync_all_scales)
            self.root.after_idle(self._fit_window_to_content)
            return

        self._set_tuning_state(True)
        self._update_run_button_state()
        lines = [f"Loaded: {path.name}", "Auto-update runs after you change parameters."]
        if layout_notes:
            lines.extend(["", "Layout (not used by current model):"])
            lines.extend(f"  • {m}" for m in layout_notes)
        self._set_results_display("\n".join(lines), current=False)
        self._clear_metric_tiles()
        self._set_status(f"Loaded {path.name}")
        self.root.after_idle(self._sync_all_scales)
        self.root.after_idle(self._fit_window_to_content)
        if self._auto_run_after_load:
            self._schedule_auto_sizing(50)

    def _cancel_pending_sizing(self) -> None:
        if self._debounce_after_id is not None:
            self.root.after_cancel(self._debounce_after_id)
            self._debounce_after_id = None
        self._sizing_generation += 1
        self._sizing_pending = False
        self.update_banner.configure(text="")
        self._sync_sizing_active()
        if self._sizing_inflight > 0 or not self._sizing_queue.empty():
            self.update_banner.configure(text="Updating…")
        self._schedule_queue_poll()

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
            self._set_results_display("Blocked:\n" + "\n".join(f"  • {m}" for m in messages), current=False)
            self._clear_metric_tiles()
            return
        if self._input_invalid or self._any_control_invalid():
            self._set_results_display(
                "Fix invalid tuning inputs (see owner captions) before Run sizing.", current=False
            )
            self._update_run_button_state()
            return
        self._start_sizing_run()

    def save_pdf(self) -> None:
        if (
            self._waiting_for_current_sizing()
            or not self._results_fresh
            or self.last_working_cfg is None
            or self.last_results is None
            or self.last_sens is None
        ):
            messagebox.showinfo("Save PDF", "Wait for sizing to finish (Save uses the last completed run).")
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
    app = SizerGUI(root)
    try:
        root.mainloop()
    finally:
        if not app._shutting_down:
            app._request_close()
        os._exit(0)


if __name__ == "__main__":
    main()