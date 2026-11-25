#!/usr/bin/env python3
"""Capture Round-29 GUI screenshots at 1280x800 under xvfb."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ARTIFACTS = Path("/opt/cursor/artifacts")
GEOMETRY = "1280x800+0+0"


def _grab_png(root, path: Path) -> None:
    from PIL import ImageGrab

    path.parent.mkdir(parents=True, exist_ok=True)
    root.update_idletasks()
    root.update()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img.save(path)
    print(f"wrote {path}", flush=True)


def _wait_results(app, root, *, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        root.update()
        app._poll_sizing_queue()
        if not app._sizing_active and not app._sizing_pending and app._results_fresh:
            return
        time.sleep(0.05)
    raise RuntimeError("timed out waiting for sizing")


def main() -> None:
    import tkinter as tk

    import gui
    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG, LUKE_CFG, run_sizing_report as _real_report

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    gate = threading.Event()

    def slow_report(base_cfg, controls):
        gate.wait(timeout=120.0)
        return _real_report(base_cfg, controls)

    # (a) Example config after auto-update
    root = tk.Tk()
    root.geometry(GEOMETRY)
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=True)
    _wait_results(app, root)
    _grab_png(root, ARTIFACTS / "r29-example-after-auto-update.png")
    app._cancel_pending_sizing()
    root.destroy()

    # (b) Luke config blocked
    root = tk.Tk()
    root.geometry(GEOMETRY)
    SizerGUI(root, config_path=LUKE_CFG, auto_run_after_load=False)
    root.update()
    _grab_png(root, ARTIFACTS / "r29-luke-blocked.png")
    root.destroy()

    # (c) Mid-update Updating…
    gate.clear()
    gui.run_sizing_report = slow_report
    root = tk.Tk()
    root.geometry(GEOMETRY)
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
    root.update()
    app._start_sizing_run()
    root.update()
    _grab_png(root, ARTIFACTS / "r29-mid-update.png")
    gate.set()
    _wait_results(app, root)

    # (d) Parameters pane scrolled to bottom (same session as c)
    app._tuning_canvas.configure(scrollregion=(0, 0, 360, 3200))
    app._tuning_canvas.yview_moveto(1.0)
    root.update()
    _grab_png(root, ARTIFACTS / "r29-pane-scrolled-bottom.png")
    app._cancel_pending_sizing()
    gui.run_sizing_report = _real_report
    root.destroy()


if __name__ == "__main__":
    main()