"""Slack notifications for #my-trade with rich context."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import requests

from config import Settings
from utils import get_logger, to_eastern

try:
    from scanner import ScanResult
except ImportError:
    ScanResult = None  # type: ignore


class SlackEvent(str, Enum):
    BOT = "bot"
    SCAN = "scan"
    UNIVERSE = "universe"
    SIGNAL = "signal"
    PLAN = "plan"
    TRADE = "trade"
    SKIP = "skip"
    EXIT = "exit"
    EOD = "eod"
    ERROR = "error"
    BACKTEST = "backtest"


_EMOJI = {
    SlackEvent.BOT: ":robot_face:",
    SlackEvent.SCAN: ":mag:",
    SlackEvent.UNIVERSE: ":globe_with_meridians:",
    SlackEvent.SIGNAL: ":chart_with_upwards_trend:",
    SlackEvent.PLAN: ":clipboard:",
    SlackEvent.TRADE: ":white_check_mark:",
    SlackEvent.SKIP: ":no_entry_sign:",
    SlackEvent.EXIT: ":door:",
    SlackEvent.EOD: ":sunset:",
    SlackEvent.ERROR: ":warning:",
    SlackEvent.BACKTEST: ":bar_chart:",
}


@dataclass
class ScanLine:
    symbol: str
    status: str
    detail: str = ""


@dataclass
class ScanReport:
    mode: str
    market_open: bool
    equity: float
    buying_power: float
    daily_pnl: float
    position_count: int
    pre_trade_ok: bool
    pre_trade_reason: str = ""
    notional_per_trade: float = 8.0
    eligible_count: int = 0
    session_stats: Optional[Dict[str, Any]] = None
    lines: List[ScanLine] = field(default_factory=list)

    def format_message(self) -> str:
        ts = to_eastern().strftime("%H:%M ET")
        market = "OPEN" if self.market_open else "CLOSED"
        pnl_pct = ""
        if self.equity > 0:
            pnl_pct = f" ({self.daily_pnl / self.equity * 100:+.2f}%)"

        header = (
            f"*Signal scan {ts}* | `{self.mode}` | Market *{market}*\n"
            f"Equity `${self.equity:,.2f}` | Day P&L `${self.daily_pnl:+,.2f}`{pnl_pct}\n"
            f"BP `${self.buying_power:,.2f}` | Positions *{self.position_count}* | "
            f"Watchlist *{self.eligible_count}* | Trade size `${self.notional_per_trade:.0f}`"
        )

        if self.session_stats:
            ss = self.session_stats
            header += (
                f"\n_Today: {ss.get('entries_today', 0)} entries, "
                f"{ss.get('signals_today', 0)} signals, "
                f"{ss.get('closed_trades', 0)} closed, "
                f"win rate {ss.get('win_rate', 0):.0f}%_"
            )

        if not self.pre_trade_ok:
            header += f"\n:no_entry_sign: *Gate:* {self.pre_trade_reason}"

        if not self.lines:
            body = "\n_No symbols in this pass._"
        else:
            rows = []
            for line in self.lines:
                extra = f" — {line.detail}" if line.detail else ""
                rows.append(f"• `{line.symbol}`: *{line.status}*{extra}")
            body = "\n".join(rows)

        return f"{_EMOJI[SlackEvent.SCAN]} {header}\n{body}"


class SlackNotifier:
    """Post bot activity to Slack (#my-trade)."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._log = get_logger()
        self._use_bot = bool(settings.slack_bot_token)
        self._use_webhook = bool(settings.slack_webhook_url)
        self.enabled = self._use_bot or self._use_webhook

    def post(
        self,
        event: SlackEvent,
        title: str,
        body: str = "",
        *,
        force: bool = False,
        fields: Optional[Dict[str, str]] = None,
    ) -> bool:
        if not self.enabled:
            return False
        if not force and event == SlackEvent.SCAN and not self._s.slack_notify_scans:
            return False

        emoji = _EMOJI.get(event, ":bell:")
        text = f"{emoji} *{title}*"
        if body:
            text += f"\n{body}"
        if fields:
            text += "\n" + "\n".join(f"*{k}:* `{v}`" for k, v in fields.items())

        return self._send(text)

    def post_universe_scan(self, result: "ScanResult", settings: Settings) -> bool:
        """Rich universe refresh message."""
        if not self.enabled:
            return False

        lines = []
        for s in result.eligible[:15]:
            vol_m = s.avg_volume / 1_000_000
            lines.append(
                f"`{s.symbol}` ${s.price:.2f} | {vol_m:.1f}M avg vol | _{s.source}_"
            )
        body = "\n".join(lines) if lines else "_No symbols passed filters._"

        footer = (
            f"Checked *{result.candidates_checked}* | "
            f"Rejected price: {result.rejected_price} | "
            f"Rejected volume: {result.rejected_volume}\n"
            f"Sources: `{', '.join(result.sources_used)}` | "
            f"Band ${settings.price_min:.2f}–${settings.price_max:.2f}"
        )

        return self._send(
            f"{_EMOJI[SlackEvent.UNIVERSE]} *Universe refresh* "
            f"({to_eastern().strftime('%H:%M ET')})\n"
            f"*{len(result.eligible)} eligible* (max {settings.max_scanner_results})\n"
            f"{body}\n{footer}"
        )

    def post_scan_report(self, report: ScanReport) -> bool:
        if not self.enabled:
            return False
        interesting = any(
            l.status.upper() in (
                "SIGNAL",
                "SIGNAL FIRED",
                "ENTRY",
                "EXIT",
                "ERROR",
                "PLAN REJECTED",
            )
            for l in report.lines
        )
        if not self._s.slack_notify_scans and not interesting and report.pre_trade_ok:
            return False
        return self._send(report.format_message())

    def post_signal(
        self,
        symbol: str,
        entry: float,
        stop: float,
        tp: float,
        reasons: List[str],
        price: float,
        avg_volume: float,
    ) -> bool:
        vol_m = avg_volume / 1_000_000
        risk_pct = (entry - stop) / entry * 100
        reward_pct = (tp - entry) / entry * 100
        return self.post(
            SlackEvent.SIGNAL,
            f"Signal: {symbol}",
            (
                f"Price `${price:.2f}` | 20d vol `{vol_m:.1f}M`\n"
                f"Entry `${entry:.2f}` | SL `${stop:.2f}` (-{risk_pct:.2f}%) | "
                f"TP `${tp:.2f}` (+{reward_pct:.2f}%) | R:R `{reward_pct/risk_pct:.1f}:1`\n"
                f"_{'; '.join(reasons)}_"
            ),
            force=True,
        )

    def _send(self, text: str) -> bool:
        try:
            if self._use_bot:
                return self._send_bot(text)
            return self._send_webhook(text)
        except requests.RequestException as exc:
            self._log.warning("Slack send failed: %s", exc)
            return False

    def _send_bot(self, text: str) -> bool:
        channel = self._s.slack_channel
        if not channel.startswith("#"):
            channel = f"#{channel}"
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {self._s.slack_bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={"channel": channel, "text": text, "mrkdwn": True},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            self._log.warning("Slack API error: %s", data.get("error"))
            return False
        return True

    def _send_webhook(self, text: str) -> bool:
        resp = requests.post(
            self._s.slack_webhook_url,
            json={"text": text, "mrkdwn": True},
            timeout=15,
        )
        resp.raise_for_status()
        return True
