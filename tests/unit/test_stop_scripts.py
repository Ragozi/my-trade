"""Regression checks for Windows stop scripts.

The paper bot can be started either in a titled console window or as a detached
Python subprocess through the operator API. The stop scripts must cover both.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_scheduled_stop_kills_pid_file_and_orphan_paper_bots() -> None:
    text = _read("scripts/scheduled_stop.bat")

    assert "EnableDelayedExpansion" in text
    assert "logs\\bot.pid" in text
    assert "taskkill /PID !BOTPID! /T /F" in text
    assert "scripts.paper_trade" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "Stop-Process -Id $_.ProcessId -Force" in text


def test_manual_stop_kills_pid_file_and_orphan_paper_bots() -> None:
    text = _read("Stop My-Trade.bat")

    assert "EnableDelayedExpansion" in text
    assert "logs\\bot.pid" in text
    assert "taskkill /PID !BOTPID! /T /F" in text
    assert "scripts.paper_trade" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "Stop-Process -Id $_.ProcessId -Force" in text
