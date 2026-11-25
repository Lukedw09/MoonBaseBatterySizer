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
    assert "(unset)" in app._owner_labels["radiator_temperature_k"].cget("text")
    root.destroy()


def test_every_control_has_visible_label_and_owner_caption():
    import tkinter as tk

    from gui import GUI_FIELD_LABELS, SizerGUI
    from gui_logic import EXAMPLE_CFG

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=EXAMPLE_CFG)
    root.update()
    assert set(GUI_FIELD_LABELS) == set(app._field_labels) == set(app._owner_labels)
    for ui_id, text in GUI_FIELD_LABELS.items():
        lbl = app._field_labels[ui_id]
        own = app._owner_labels[ui_id]
        assert lbl.cget("text") == text
        assert lbl.winfo_ismapped()
        assert own.winfo_ismapped()
        assert own.cget("text").startswith("owner:")
        assert len(own.cget("text")) > 6
    root.destroy()


def test_scale_widgets_exist_mapped_with_value_labels():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    expected = {"depth_of_discharge", "efficiency", "panel_efficiency", "sun_incidence_cosine"}
    root = tk.Tk()
    app = SizerGUI(root, config_path=EXAMPLE_CFG)
    root.update()
    assert set(app._scales) == expected
    for uid, scale in app._scales.items():
        assert scale.winfo_ismapped()
        assert int(scale.cget("showvalue")) == 1
        assert scale.cget("state") == tk.NORMAL
        assert uid in app._field_labels
    root.destroy()


def test_luke_blocked_yaml_unset_controls_not_invented_values():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import LUKE_CFG, UI_CONTROL_TO_CFG_KEYS
    from sizer import param_value

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=LUKE_CFG)
    root.update()
    null_ui_keys = (
        "n_packs",
        "packaging_insulation_mass_factor",
        "radiator_temperature_k",
        "radiator_emissivity",
        "panel_efficiency",
        "sun_incidence_cosine",
    )
    for ui_id in null_ui_keys:
        assert param_value(app.base_cfg, *UI_CONTROL_TO_CFG_KEYS[ui_id]) is None
        assert "TODO-luke" in app._owner_labels[ui_id].cget("text")
        assert "(unset)" in app._owner_labels[ui_id].cget("text")
        if ui_id in app._scale_ui_ids:
            assert not app._scales[ui_id].winfo_ismapped()
            assert app._unset_placeholders[ui_id].winfo_ismapped()
        else:
            assert app.controls[ui_id].get() == "unset"
    root.destroy()


def test_blocked_scale_interaction_does_not_change_value_or_owner():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import LUKE_CFG

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=LUKE_CFG)
    root.update()
    assert not app._controls_editable
    eff = app._scales["efficiency"]
    v0 = float(eff.get())
    cap_before = app._owner_labels["efficiency"].cget("text")
    eff.event_generate("<Button-1>", x=40, y=8)
    eff.event_generate("<B1-Motion>", x=eff.winfo_width() - 10, y=8)
    eff.event_generate("<ButtonRelease-1>", x=eff.winfo_width() - 10, y=8)
    root.update()
    assert float(eff.get()) == pytest.approx(v0)
    assert app._owner_labels["efficiency"].cget("text") == cap_before
    assert "ui-override" not in cap_before
    root.destroy()


def test_invalid_primary_w_caption_and_run_disabled():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=EXAMPLE_CFG)
    root.update()
    assert str(app.run_btn.cget("state")) == tk.NORMAL
    app.controls["n_packs"].set("abc")
    root.update()
    assert "invalid" in app._owner_labels["n_packs"].cget("text")
    assert str(app.run_btn.cget("state")) == tk.DISABLED
    root.destroy()


def test_save_pdf_disabled_then_reflects_n_packs_after_rerun(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    import tkinter as tk
    from pypdf import PdfReader

    import gui
    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    out_pdf = tmp_path / "gui_saved.pdf"
    monkeypatch.setattr(gui.filedialog, "asksaveasfilename", lambda **kw: str(out_pdf))
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=EXAMPLE_CFG)
    root.update()
    app.run_sizing()
    root.update()
    assert str(app.pdf_btn.cget("state")) == tk.NORMAL
    app.controls["n_packs"].set("2")
    root.update()
    assert str(app.pdf_btn.cget("state")) == tk.DISABLED
    app.run_sizing()
    root.update()
    assert app.controls["n_packs"].get() == "2"
    app.save_pdf()
    text = "\n".join((p.extract_text() or "") for p in PdfReader(out_pdf).pages)
    assert "geometry.n_packs: 2" in text
    root.destroy()


def test_n_packs_spinbox_keeps_config_value_above_slider_max(tmp_path):
    import copy

    import tkinter as tk
    import yaml

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG
    from sizer import load_config, param_value

    cfg = copy.deepcopy(load_config(EXAMPLE_CFG))
    cfg["geometry"]["n_packs"]["value"] = 32
    cfg_path = tmp_path / "n32.yaml"
    cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=cfg_path)
    root.update()
    assert app.controls["n_packs"].get() == "32"
    assert int(param_value(app.base_cfg, "geometry", "n_packs")) == 32
    root.destroy()