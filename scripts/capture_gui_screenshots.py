#!/usr/bin/env python3
"""Capture GUI screenshots (a–c) at 1280x800 under xvfb."""

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


def main() -> None:
    import tkinter as tk

    import gui
    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG, LUKE_CFG, run_sizing_report as _real_report

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    gate = threading.Event()
    digests: dict[str, str] = {}

    def slow_report(base_cfg, controls):
        gate.wait(timeout=120.0)
        return _real_report(base_cfg, controls)

    root = tk.Tk()
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=True)
    _prime_window(root, app)
    _wait_results(app, root)
    digests["a"] = _grab_png(root, ARTIFACTS / "r32-example-after-auto-update.png")
    root.destroy()

    root = tk.Tk()
    app_b = SizerGUI(root, config_path=LUKE_CFG, auto_run_after_load=False)
    _prime_window(root, app_b)
    digests["b"] = _grab_png(root, ARTIFACTS / "r32-luke-blocked.png")
    root.destroy()

    gate.clear()
    gui.run_sizing_report = slow_report
    root = tk.Tk()
    app_c = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=True)
    _prime_window(root, app_c)
    _wait_results(app_c, root)
    app_c.controls["n_packs"].set("6")
    app_c._mark_results_stale()
    app_c._start_sizing_run()
    for _ in range(30):
        root.update()
        time.sleep(0.05)
    digests["c"] = _grab_png(root, ARTIFACTS / "r32-mid-update.png")
    gate.set()
    _wait_results(app_c, root)
    gui.run_sizing_report = _real_report
    root.destroy()

    print("md5 summary:", digests, flush=True)
    assert len({digests["a"], digests["b"], digests["c"]}) == 3


if __name__ == "__main__":
    main()