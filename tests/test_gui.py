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
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
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
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
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
    app = SizerGUI(root, config_path=LUKE_CFG, auto_run_after_load=False)
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
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
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
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
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
    app = SizerGUI(root, config_path=LUKE_CFG, auto_run_after_load=False)
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


def _assert_blocked_scale_ignores_interaction(scale, owner_label, v0: float) -> None:
    import tkinter as tk

    cap_before = owner_label.cget("text")
    w = max(scale.winfo_width(), 80)
    for seq in (
        ("<Button-1>", "<B1-Motion>", "<ButtonRelease-1>"),
        ("<Button-2>", "<B2-Motion>", "<ButtonRelease-2>"),
        ("<Button-3>", "<B3-Motion>", "<ButtonRelease-3>"),
    ):
        scale.event_generate(seq[0], x=40, y=8)
        scale.event_generate(seq[1], x=w - 10, y=8)
        scale.event_generate(seq[2], x=w - 10, y=8)
    scale.event_generate("<Key>", keysym="Right")
    scale.event_generate("<Key>", keysym="Up")
    scale.event_generate("<MouseWheel>", delta=120)
    scale.update_idletasks()
    assert float(scale.get()) == pytest.approx(v0)
    assert owner_label.cget("text") == cap_before
    assert "ui-override" not in cap_before


def test_blocked_scales_ignore_mouse_keys_and_wheel():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import LUKE_CFG

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=LUKE_CFG, auto_run_after_load=False)
    root.update()
    assert not app._controls_editable
    for ui_id in ("depth_of_discharge", "efficiency"):
        scale = app._scales[ui_id]
        _assert_blocked_scale_ignores_interaction(
            scale, app._owner_labels[ui_id], float(scale.get())
        )
    root.destroy()


def test_run_sizing_n_packs_249_shows_leg_mesh_error():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
    root.update()
    app.controls["n_packs"].set("249")
    app.run_sizing()
    _wait_sizing_idle(app, root)
    body = app.results_text.get("1.0", tk.END)
    assert "n_packs too large for leg thermal mesh" in body
    root.destroy()


def test_invalid_primary_w_caption_and_run_disabled():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
    root.update()
    assert str(app.run_btn.cget("state")) == tk.NORMAL
    app.controls["n_packs"].set("abc")
    root.update()
    assert "invalid" in app._owner_labels["n_packs"].cget("text")
    assert str(app.run_btn.cget("state")) == tk.DISABLED
    root.destroy()


def test_save_pdf_passes_last_working_cfg_not_live_controls(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    import tkinter as tk
    from pypdf import PdfReader

    import gui
    import gui_logic
    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG
    from sizer import param_value

    out_pdf = tmp_path / "gui_saved.pdf"
    captured: list = []
    real_write = gui_logic.write_sizing_pdf

    def spy_write(path, cfg, results, sens):
        captured.append(cfg)
        real_write(path, cfg, results, sens)

    monkeypatch.setattr(gui_logic, "write_sizing_pdf", spy_write)
    monkeypatch.setattr(gui, "write_sizing_pdf", spy_write)
    monkeypatch.setattr(gui.filedialog, "asksaveasfilename", lambda **kw: str(out_pdf))
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
    root.update()
    app.controls["n_packs"].set("2")
    app.run_sizing()
    _wait_sizing_idle(app, root)
    assert param_value(app.last_working_cfg, "geometry", "n_packs") == 2
    app.controls["n_packs"].set("32")
    root.update()
    assert str(app.pdf_btn.cget("state")) == tk.DISABLED
    # If stale guard were removed, save must still pass last_working_cfg (not live widgets).
    app._results_fresh = True
    app.pdf_btn.configure(state=tk.NORMAL)
    app.save_pdf()
    assert len(captured) == 1
    assert captured[0] is app.last_working_cfg
    assert param_value(captured[0], "geometry", "n_packs") == 2
    assert param_value(captured[0], "geometry", "n_packs") != 32
    text = "\n".join((p.extract_text() or "") for p in PdfReader(out_pdf).pages)
    assert "geometry.n_packs: 2" in text
    root.destroy()


def _wait_sizing_idle(app, root, *, timeout_ms: int = 20000) -> None:
    import time

    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        root.update()
        app._poll_sizing_queue()
        if not app._sizing_active and not app._sizing_pending and app._sizing_queue.empty():
            return
        time.sleep(0.02)
    pytest.fail("sizing did not finish")


def test_launch_auto_loads_program_config_yaml():
    import tkinter as tk

    from gui import SizerGUI, program_config_path

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, auto_run_after_load=False)
    root.update()
    assert app.loaded_path == program_config_path()
    assert app.config_name_label.cget("text") == program_config_path().name
    root.destroy()


def test_scale_motion_does_not_run_sizing(monkeypatch):
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    starts: list[int] = []
    orig = SizerGUI._start_sizing_run

    def spy_start(self):
        starts.append(1)

    monkeypatch.setattr(SizerGUI, "_start_sizing_run", spy_start)

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
    root.update()
    starts.clear()
    scale = app._scales["efficiency"]
    w = max(scale.winfo_width(), 80)
    scale.event_generate("<Button-1>", x=40, y=8)
    scale.event_generate("<B1-Motion>", x=w - 10, y=8)
    root.update()
    assert not starts
    scale.event_generate("<ButtonRelease-1>", x=w - 10, y=8)
    root.update()
    assert starts == [1]
    orig(app)
    root.destroy()


def test_only_latest_sizing_result_shown(monkeypatch):
    import threading
    import time
    import tkinter as tk

    import gui
    import gui_logic

    calls = [0]
    lock = threading.Lock()
    _real = gui_logic.run_sizing_report

    def slow_report(base_cfg, controls):
        with lock:
            calls[0] += 1
            seq = calls[0]
        if seq == 1:
            time.sleep(0.25)
            return base_cfg, "STALE_RUN_MARKER\nstale", {}, {}
        return _real(base_cfg, controls)

    monkeypatch.setattr(gui, "run_sizing_report", slow_report)

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    root = tk.Tk()
    root.withdraw()
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
    root.update()
    app._start_sizing_run()
    app._start_sizing_run()
    _wait_sizing_idle(app, root, timeout_ms=30000)
    body = app.results_text.get("1.0", tk.END)
    assert "STALE_RUN_MARKER" not in body
    app._cancel_pending_sizing()
    root.destroy()


def test_save_pdf_disabled_while_sizing_updates(monkeypatch):
    import threading
    import tkinter as tk

    import gui
    import gui_logic

    gate = threading.Event()
    _real = gui_logic.run_sizing_report

    def slow_report(base_cfg, controls):
        gate.wait(timeout=2.0)
        return _real(base_cfg, controls)

    monkeypatch.setattr(gui, "run_sizing_report", slow_report)

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    root = tk.Tk()
    root.withdraw()
    gate.set()
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
    root.update()
    gate.clear()
    app.controls["n_packs"].set("4")
    app._start_sizing_run()
    root.update()
    assert app._sizing_active
    assert str(app.pdf_btn.cget("state")) == tk.DISABLED
    gate.set()
    _wait_sizing_idle(app, root)
    assert str(app.pdf_btn.cget("state")) == tk.NORMAL
    app._cancel_pending_sizing()
    root.destroy()


def test_tuning_canvas_wheel_scrolls_without_changing_scale():
    import tkinter as tk

    from gui import SizerGUI
    from gui_logic import EXAMPLE_CFG

    root = tk.Tk()
    root.geometry("900x420")
    app = SizerGUI(root, config_path=EXAMPLE_CFG, auto_run_after_load=False)
    app._fit_window_to_content()
    root.update_idletasks()
    app._tuning_canvas.configure(scrollregion=(0, 0, 360, 3200))
    app._tuning_canvas.yview_moveto(0.0)
    root.update()
    scale = app._scales["efficiency"]
    v0 = float(scale.get())
    app._tuning_canvas.update_idletasks()
    top_before = float(app._tuning_canvas.yview()[0])
    app._tuning_canvas.event_generate("<Enter>")

    class _WheelEvt:
        widget = app._tuning_canvas
        delta = -120
        num = 5

    app._on_tuning_wheel(_WheelEvt())
    root.update()
    top_after = float(app._tuning_canvas.yview()[0])
    assert top_after > top_before
    assert float(scale.get()) == pytest.approx(v0)
    scale.event_generate("<MouseWheel>", delta=120)
    root.update()
    assert float(scale.get()) == pytest.approx(v0)
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
    app = SizerGUI(root, config_path=cfg_path, auto_run_after_load=False)
    root.update()
    assert app.controls["n_packs"].get() == "32"
    assert int(param_value(app.base_cfg, "geometry", "n_packs")) == 32
    root.destroy()