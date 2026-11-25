"""Tkinter-only GUI tests (skipped when tkinter or display unavailable)."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("tkinter")
pytestmark = pytest.mark.skipif(
    not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"),
    reason="No display for Tk widget tests",
)


def test_gui_module_imports_with_tkinter():
    import gui  # noqa: F401

    assert gui.UI_CONTROL_TO_CFG_KEYS is not None


def test_horizontal_scale_shows_value_for_double_var():
    import tkinter as tk

    from gui import _horizontal_scale

    root = tk.Tk()
    root.withdraw()
    var = tk.DoubleVar(value=0.8)
    scale = _horizontal_scale(root, var, from_=0.05, to=1.0, resolution=0.01)
    scale.update_idletasks()
    assert float(var.get()) == pytest.approx(0.8)
    assert int(scale.cget("showvalue")) == 1
    root.destroy()