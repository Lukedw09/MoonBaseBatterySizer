#!/usr/bin/env python3
"""Subprocess probe: WM_DELETE_WINDOW during sizing update; must exit 0."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gui  # noqa: E402
import gui_logic  # noqa: E402
from gui import SizerGUI  # noqa: E402
from gui_logic import EXAMPLE_CFG  # noqa: E402

_gate = threading.Event()
_real = gui.run_sizing_report


def _slow_report(base_cfg, controls):
    if not _gate.is_set():
        _gate.wait(timeout=60.0)
    return _real(base_cfg, controls)


gui.run_sizing_report = _slow_report


def _trigger_wm_delete_window(root) -> None:
    cmd = root.tk.call("wm", "protocol", root._w, "WM_DELETE_WINDOW")
    if cmd:
        root.tk.call("eval", cmd)


def main() -> None:
    import tkinter as tk

    root = tk.Tk()
    root.geometry("900x700+0+0")
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
    root.update_idletasks()
    root.update()
    app._start_sizing_run()

    def _close_soon() -> None:
        root.update_idletasks()
        _trigger_wm_delete_window(root)

    root.after(250, _close_soon)
    root.mainloop()


if __name__ == "__main__":
    main()