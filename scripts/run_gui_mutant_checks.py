#!/usr/bin/env python3
"""Apply real gui.py mutants one at a time; print which tests fail."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "gui.py"

MUTANTS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "save_pdf uses _sizing_active guard",
        [
            (
                "if (\n            self._waiting_for_current_sizing()",
                "if (\n            self._sizing_active",
            ),
        ],
    ),
    (
        "pdf button never waits (always enabled)",
        [
            (
                "def _update_pdf_button_state(self) -> None:\n        if self._waiting_for_current_sizing():",
                "def _update_pdf_button_state(self) -> None:\n        if False:",
            ),
        ],
    ),
    (
        "no snapshot-mismatch rerun",
        [
            (
                "                if snapshot and not self._controls_match_snapshot(snapshot):\n"
                "                    self._set_status(\"Inputs changed — updating…\")\n"
                "                    self._mark_results_stale()\n"
                "                    self._schedule_auto_sizing(50)\n",
                "                if False:\n"
                "                    self._set_status(\"Inputs changed — updating…\")\n"
                "                    self._mark_results_stale()\n"
                "                    self._schedule_auto_sizing(50)\n",
            ),
        ],
    ),
    (
        "no scale key debounce",
        [("SCALE_KEY_DEBOUNCE_MS = 300", "SCALE_KEY_DEBOUNCE_MS = 0")],
    ),
    (
        "single-item queue drain",
        [
            (
                "        while True:\n            try:\n                run_id, payload = self._sizing_queue.get_nowait()\n            except queue.Empty:\n                break\n            self._finish_sizing_run(run_id, payload)",
                "        try:\n            run_id, payload = self._sizing_queue.get_nowait()\n        except queue.Empty:\n            run_id = None\n        if run_id is not None:\n            self._finish_sizing_run(run_id, payload)",
            ),
        ],
    ),
    (
        "ignore margin threshold (hard-coded 6K amber)",
        [
            (
                "    margin_thr: Optional[float] = None\n    if cfg is not None:\n        thr = param_value(cfg, \"battery\", \"lipo_margin_threshold_k\")\n        if thr is not None:\n            margin_thr = float(thr)",
                "    margin_thr: Optional[float] = 6.0",
            ),
        ],
    ),
    (
        "reload without generation bump",
        [
            (
                "    def _cancel_pending_sizing(self) -> None:\n        if self._debounce_after_id is not None:\n"
                "            self.root.after_cancel(self._debounce_after_id)\n"
                "            self._debounce_after_id = None\n"
                "        self._sizing_generation += 1\n",
                "    def _cancel_pending_sizing(self) -> None:\n        if self._debounce_after_id is not None:\n"
                "            self.root.after_cancel(self._debounce_after_id)\n"
                "            self._debounce_after_id = None\n",
            ),
        ],
    ),
    (
        "no stale generation guard in finish",
        [
            (
                "        stale = run_id != self._sizing_generation\n        if not stale:",
                "        stale = False\n        if not stale:",
            ),
        ],
    ),
]

TESTS: dict[str, str] = {
    "save_pdf uses _sizing_active guard": "test_save_pdf_enabled_while_stale_worker_still_running",
    "pdf button never waits (always enabled)": "test_save_pdf_refuses_while_current_generation_in_flight",
    "no snapshot-mismatch rerun": "test_snapshot_mismatch_schedules_auto_sizing",
    "no scale key debounce": "test_scale_key_debounce_single_run_for_held_key",
    "single-item queue drain": "test_poll_sizing_queue_drains_all_pending_results",
    "ignore margin threshold (hard-coded 6K amber)": "test_margin_tile_unset_threshold_no_amber_for_positive_margin",
    "reload without generation bump": "test_reload_blocked_config_while_example_run_inflight",
    "no stale generation guard in finish": "test_stale_worker_finishes_last_discarded",
}


def _run_test(test_name: str, gui_source: str) -> int:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
        tmp.write(gui_source)
        tmp_path = Path(tmp.name)
    # patch gui module by replacing file in subprocess is heavy; use env + copy
    backup = GUI.read_text(encoding="utf-8")
    try:
        GUI.write_text(gui_source, encoding="utf-8")
        cmd = [
            "xvfb-run",
            "-a",
            sys.executable,
            "-m",
            "pytest",
            f"tests/test_gui.py::{test_name}",
            "-q",
            "--tb=no",
        ]
        return subprocess.run(cmd, cwd=ROOT, timeout=180).returncode
    finally:
        GUI.write_text(backup, encoding="utf-8")
        tmp_path.unlink(missing_ok=True)


def main() -> None:
    original = GUI.read_text(encoding="utf-8")
    print("mutant\tfailing_test\texit")
    for label, replacements in MUTANTS:
        mutated = original
        for old, new in replacements:
            if old not in mutated:
                print(f"{label}\tMUTATION_NOT_APPLIED\t2", flush=True)
                mutated = ""
                break
            mutated = mutated.replace(old, new, 1)
        if not mutated:
            continue
        test = TESTS[label]
        code = _run_test(test, mutated)
        fail = "yes" if code != 0 else "no"
        print(f"{label}\t{test}\t{fail}", flush=True)


if __name__ == "__main__":
    main()