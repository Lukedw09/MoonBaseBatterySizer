"""Tkinter-only GUI tests (skipped when tkinter or display unavailable)."""

from __future__ import annotations

import os
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
    from gui_logic import UI_CONTROL_TO_CFG_KEYS

    assert UI_CONTROL_TO_CFG_KEYS is not None


def _assert_scale_inside_row(scale) -> None:
    from gui import SCALE_LENGTH

    row = scale.master
    scale.update_idletasks()
    row.update_idletasks()
    sx, _ = scale.winfo_x(), scale.winfo_y()
    sw, sh = scale.winfo_width(), scale.winfo_height()
    rw = row.winfo_width()
    assert sw >= min(SCALE_LENGTH - 4, 160), f"scale too narrow: {sw}"
    assert sh >= 18
    assert sx >= 0
    assert sx + sw <= rw + 2, f"scale right {sx + sw} exceeds row width {rw}"


def test_fraction_scales_display_after_example_load():
    import tkinter as tk

    from gui import TUNING_PANEL_MIN_WIDTH, SizerGUI
    from gui_logic import EXAMPLE_CFG

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=EXAMPLE_CFG)
    root.update_idletasks()
    root.deiconify()
    app._sync_all_scales()
    app._fit_window_to_content()
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
        _assert_scale_inside_row(scale)

    assert app._tuning_pane.winfo_width() >= TUNING_PANEL_MIN_WIDTH - 8

    root.destroy()


def test_all_scales_fit_row_at_max_value():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    root = tk.Tk()
    app = SizerGUI(root, config_path=EXAMPLE_CFG)
    app._fit_window_to_content()
    root.update()

    for ui_id, scale in app._scales.items():
        end = float(scale.cget("to"))
        scale.set(end)
    app._sync_all_scales()
    root.update_idletasks()

    for scale in app._scales.values():
        assert scale.cget("state") == tk.NORMAL
        _assert_scale_inside_row(scale)
        row = scale.master
        assert row.winfo_ismapped()
        canvas = app._tuning_canvas
        assert canvas.winfo_ismapped()
        crx = canvas.winfo_rootx()
        srx = scale.winfo_rootx()
        sw = scale.winfo_width()
        assert srx + sw <= crx + canvas.winfo_width() + 2

    root.destroy()


def test_luke_config_read_only_tuning_run_save_disabled():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import LUKE_CFG

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=LUKE_CFG)
    root.update()
    assert str(app.run_btn.cget("state")) == tk.DISABLED
    assert str(app.pdf_btn.cget("state")) == tk.DISABLED
    assert "luke" in app._owner_labels["pack_volumetric_energy_density_wh_per_m3"].cget("text").lower()
    assert "unset in YAML" in app._owner_labels["radiator_temperature_k"].cget("text")
    root.destroy()


def test_save_pdf_disabled_after_control_change():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=EXAMPLE_CFG)
    root.update()
    app.run_sizing()
    root.update()
    assert str(app.pdf_btn.cget("state")) == tk.NORMAL
    app.controls["n_packs"].set(2)
    root.update()
    assert str(app.pdf_btn.cget("state")) == tk.DISABLED
    root.destroy()


def test_n_packs_spinbox_keeps_config_value_above_slider_max():
    import copy

    import tkinter as tk
    import yaml

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG
    from sizer import load_config, param_value

    cfg_path = ROOT / "artifacts" / "_n32_config.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = copy.deepcopy(load_config(EXAMPLE_CFG))
    cfg["geometry"]["n_packs"]["value"] = 32
    cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=cfg_path)
    root.update()
    assert int(app.controls["n_packs"].get()) == 32
    assert int(param_value(app.base_cfg, "geometry", "n_packs")) == 32
    root.destroy()