#!/usr/bin/env python3
"""Capture GUI screenshots at 1280x800 under xvfb (Round 29/30)."""

from __future__ import annotations

import hashlib
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACTS = Path("/opt/cursor/artifacts")
GEOMETRY = "1280x800+0+0"


def _grab_png(root, path: Path) -> str:
    from PIL import ImageGrab

    path.parent.mkdir(parents=True, exist_ok=True)
    root.update_idletasks()
    root.update()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img.save(path)
    digest = hashlib.md5(path.read_bytes()).hexdigest()
    print(f"wrote {path} md5={digest}", flush=True)
    return digest


def _prime_window(root, app) -> None:
    root.deiconify()
    root.geometry(GEOMETRY)
    root.update_idletasks()
    app.layout_panes_for_display()
    app.tuning_frame.update_idletasks()
    app._tuning_canvas.configure(scrollregion=app._tuning_canvas.bbox("all"))
    root.update()


def _wait_results(app, root, *, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        app._poll_sizing_queue()
        if not app._sizing_active and not app._sizing_pending and app._results_fresh:
            return
        time.sleep(0.05)
    raise RuntimeError("timed out waiting for sizing")


def _scroll_tuning_to_bottom(app, root) -> None:
    app.tuning_frame.update_idletasks()
    bbox = app._tuning_canvas.bbox("all")
    if bbox:
        app._tuning_canvas.configure(scrollregion=bbox)
    root.update()
    for _ in range(80):
        app._tuning_canvas.yview_scroll(3, "units")
        root.update()
    app._tuning_canvas.yview_moveto(1.0)
    root.update()


def main() -> None:
    import tkinter as tk

    import gui
    from gui import SizerGUI, TUNING_PANEL_MIN_WIDTH
    from gui_logic import EXAMPLE_CFG, LUKE_CFG, run_sizing_report as _real_report

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    gate = threading.Event()
    digests: dict[str, str] = {}

    def slow_report(base_cfg, controls):
        gate.wait(timeout=120.0)
        return _real_report(base_cfg, controls)

    # (a) Example config after auto-update
    root = tk.Tk()
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=True)
    _prime_window(root, app)
    _wait_results(app, root)
    digests["a"] = _grab_png(root, ARTIFACTS / "r30-example-after-auto-update.png")
    assert app._tuning_pane.winfo_width() >= TUNING_PANEL_MIN_WIDTH - 16
    app._cancel_pending_sizing()
    root.destroy()

    # (b) Luke config blocked (results pane)
    root = tk.Tk()
    app_b = SizerGUI(root, config_path=LUKE_CFG, auto_run_after_load=False)
    _prime_window(root, app_b)
    digests["b"] = _grab_png(root, ARTIFACTS / "r30-luke-blocked.png")
    root.destroy()

    # (e) Luke config — parameter pane with unset fields visible
    root = tk.Tk()
    app_e = SizerGUI(root, config_path=LUKE_CFG, auto_run_after_load=False)
    _prime_window(root, app_e)
    app_e.tuning_frame.update_idletasks()
    app_e._tuning_canvas.configure(scrollregion=app_e._tuning_canvas.bbox("all"))
    for _ in range(24):
        app_e._tuning_canvas.yview_scroll(2, "units")
        root.update()
    digests["e"] = _grab_png(root, ARTIFACTS / "r30-luke-parameters-unset.png")
    root.destroy()

    # (c) Mid-update: prior results visible + Updating…
    gui.run_sizing_report = _real_report
    root = tk.Tk()
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
    _prime_window(root, app)
    app.run_sizing()
    _wait_results(app, root)
    prior = app._last_valid_results_text or ""
    assert "Pack mass" in prior
    gate.clear()
    gui.run_sizing_report = slow_report
    app.controls["n_packs"].set("6")
    app._start_sizing_run()
    root.update()
    assert "Updating" in app.update_banner.cget("text")
    assert "Pack mass" in app.results_text.get("1.0", tk.END)
    digests["c"] = _grab_png(root, ARTIFACTS / "r30-mid-update.png")
    gate.set()
    gui.run_sizing_report = _real_report
    app._cancel_pending_sizing()
    root.destroy()

    # (d) Parameters pane scrolled to bottom
    root = tk.Tk()
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
    _prime_window(root, app)
    _scroll_tuning_to_bottom(app, root)
    y0, y1 = app._tuning_canvas.yview()
    assert y1 > 0.95, f"scroll not at bottom: {y0}, {y1}"
    digests["d"] = _grab_png(root, ARTIFACTS / "r30-pane-scrolled-bottom.png")
    assert digests["d"] != digests["a"], "scroll shot must differ from (a)"
    root.destroy()

    print("md5 summary:", digests, flush=True)


if __name__ == "__main__":
    main()