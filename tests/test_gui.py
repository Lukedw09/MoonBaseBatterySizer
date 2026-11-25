"""Tkinter-only GUI tests (skipped when tkinter or display unavailable)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("tkinter")

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="No display for Tk widget tests",
)


def test_gui_module_imports_with_tkinter():
    import gui  # noqa: F401

    assert gui.UI_CONTROL_TO_CFG_KEYS is not None


def test_fraction_scales_display_after_example_load():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=EXAMPLE_CFG)
    root.update_idletasks()
    root.geometry("1150x760")
    root.deiconify()
    root.update()
    app._sync_all_scales()
    root.update()

    dod = app._scales["depth_of_discharge"]
    eff = app._scales["efficiency"]
    panel = app._scales["panel_efficiency"]

    assert float(dod.get()) == pytest.approx(0.8, abs=0.011)
    assert float(eff.get()) == pytest.approx(0.9, abs=0.011)
    assert float(panel.get()) == pytest.approx(0.28, abs=0.011)

    for scale in (dod, eff, panel):
        assert int(scale.cget("showvalue")) == 1
        assert scale.cget("state") == tk.NORMAL
        assert scale.winfo_width() >= 180
        assert scale.winfo_height() >= 20

    for uid in ("depth_of_discharge", "efficiency"):
        scale = app._scales[uid]
        scale.event_generate("<Enter>")
        root.update()
        assert scale.winfo_ismapped()
        assert scale.winfo_viewable()
        bx = scale.winfo_x()
        by = scale.winfo_y()
        bw = scale.winfo_width()
        bh = scale.winfo_height()
        assert bw >= 180 and bh >= 18
        assert bx >= 0 and by >= 0

    root.destroy()