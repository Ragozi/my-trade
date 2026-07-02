"""Bot process manager: start/stop the paper-trading loop as a subprocess.

State is persisted in ``logs/bot.pid`` and ``logs/bot_status.json`` so the API
can report running/stopped and last-cycle metadata across restarts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BotStatus:
    running: bool
    pid: int | None
    started_at: str | None
    last_cycle_at: str | None
    cycles_today: int
    halted: bool
    halt_reason: str | None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def pid_path(log_dir: str) -> Path:
    return Path(log_dir) / "bot.pid"


def status_path(log_dir: str) -> Path:
    return Path(log_dir) / "bot_status.json"


def log_path(log_dir: str) -> Path:
    return Path(log_dir) / "paper.log"


def _is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_status_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return raw
    except (json.JSONDecodeError, OSError):
        return {}


def write_status_file(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def get_bot_status(log_dir: str) -> BotStatus:
    pid_file = pid_path(log_dir)
    status_file = status_path(log_dir)
    raw = read_status_file(status_file)
    pid: int | None = None
    running = False
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            running = _is_alive(pid)
        except ValueError:
            pid = None
    if pid is not None and not running:
        pid_file.unlink(missing_ok=True)
        pid = None
    return BotStatus(
        running=running,
        pid=pid,
        started_at=raw.get("started_at"),
        last_cycle_at=raw.get("last_cycle_at"),
        cycles_today=int(raw.get("cycles_today", 0)),
        halted=bool(raw.get("halted", False)),
        halt_reason=raw.get("halt_reason"),
    )


def _enumerate_paper_bot_pids() -> list[int]:
    """Return PIDs for any running ``scripts.paper_trade`` processes."""
    if sys.platform == "win32":
        script = (
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*scripts.paper_trade*' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        return [int(line.strip()) for line in out.stdout.splitlines() if line.strip().isdigit()]
    try:
        out = subprocess.run(
            ["pgrep", "-f", "scripts.paper_trade"],
            capture_output=True,
            text=True,
            check=False,
        )
        return [int(x) for x in out.stdout.split() if x.strip().isdigit()]
    except FileNotFoundError:
        return []


def _kill_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def stop_all_paper_bots(log_dir: str) -> list[int]:
    """Stop every paper bot process (pid file + any orphans)."""
    stopped: list[int] = []
    for pid in _enumerate_paper_bot_pids():
        if pid not in stopped:
            _kill_pid(pid)
            stopped.append(pid)
    pid_file = pid_path(log_dir)
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            if pid not in stopped:
                _kill_pid(pid)
                stopped.append(pid)
        except ValueError:
            pass
        pid_file.unlink(missing_ok=True)
    return stopped


def start_bot(log_dir: str) -> tuple[bool, str]:
    stop_all_paper_bots(log_dir)
    root = _repo_root()
    log_file = log_path(log_dir)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_file, "a", encoding="utf-8")  # noqa: SIM115
    cmd = [sys.executable, "-m", "scripts.paper_trade"]
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    proc = subprocess.Popen(
        cmd,
        cwd=root,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    pid_path(log_dir).write_text(str(proc.pid), encoding="utf-8")
    now = datetime.now(UTC).isoformat()
    write_status_file(
        status_path(log_dir),
        {
            "started_at": now,
            "last_cycle_at": None,
            "cycles_today": 0,
            "halted": False,
            "halt_reason": None,
        },
    )
    return True, f"Bot started (pid {proc.pid})"


def stop_bot(log_dir: str) -> tuple[bool, str]:
    current = get_bot_status(log_dir)
    if not current.running or current.pid is None:
        pid_path(log_dir).unlink(missing_ok=True)
        return True, "Bot was not running"
    pid = current.pid
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    else:
        os.kill(pid, 15)
    pid_path(log_dir).unlink(missing_ok=True)
    return True, f"Bot stopped (pid {pid})"


def tail_log(log_dir: str, n: int = 100) -> list[str]:
    path = log_path(log_dir)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-max(n, 1) :]


def record_cycle(
    log_dir: str,
    *,
    timestamp: datetime,
    halted: bool,
    halt_reason: str | None,
) -> None:
    """Called by the paper runner after each cycle to refresh bot_status.json."""
    path = status_path(log_dir)
    raw = read_status_file(path)
    today = timestamp.date().isoformat()
    cycles = int(raw.get("cycles_today", 0))
    if raw.get("cycle_day") != today:
        cycles = 0
    cycles += 1
    write_status_file(
        path,
        {
            "started_at": raw.get("started_at"),
            "last_cycle_at": timestamp.isoformat(),
            "cycles_today": cycles,
            "cycle_day": today,
            "halted": halted,
            "halt_reason": halt_reason,
        },
    )
