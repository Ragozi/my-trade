"""TradingOrchestrator: the thin loop that coordinates the deterministic core.

It owns *sequencing and daily state*, not trading math — every decision is
delegated to already-tested pure layers:

    Data (bars)  ->  Strategy (signal/exit)  ->  Risk (gate, inside execution)
                                              ->  Execution (orders)

Safety invariants preserved here:
  * Exits are managed every cycle, even when new entries are halted.
  * No entry is ever sent without the risk gate approving (the execution adapter
    re-runs ``evaluate_trade``); the orchestrator additionally halts entries on
    circuit-breaker / daily-loss.
  * Daily state is persisted after every mutation so restarts never double-count.
  * No research/Claude calls unless a ``ResearchAdvisor`` is injected (Phase 4).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Protocol

import pandas as pd

from my_trade.core.execution import EntryIntent, ExecutionOutcome
from my_trade.core.risk import (
    RiskLimits,
    is_circuit_breaker_tripped,
    is_daily_loss_limit_hit,
    is_daily_profit_target_hit,
)
from my_trade.data import MarketDataProvider, normalize_symbol
from my_trade.research.models import ClaudeProposal

from .account import AccountProvider, AccountSnapshot, Position
from .models import ActionKind, CycleAction, CycleResult, HaltReason
from .state import (
    DailyState,
    build_account_state,
    clear_position,
    entry_time_for,
    mark_halt_lesson_logged,
    record_entry,
    rollover_if_new_day,
)
from .store import DailyStateStore

if TYPE_CHECKING:
    from my_trade.core.risk import AccountState
    from my_trade.core.strategy.models import ScanEvaluation, Signal
    from my_trade.research.advisor import ResearchAdvisor
    from my_trade.research.evaluation import ResearchEvaluationStore
    from my_trade.research.knowledge import TradeKnowledgeStore
    from my_trade.research.memory import ResearchMemoryStore


class StrategyEngine(Protocol):
    def detect_entry(
        self,
        symbol: str,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame,
        df_15m: pd.DataFrame,
        now: datetime | None = None,
    ) -> tuple[Signal | None, ScanEvaluation]: ...

    def detect_exit(
        self,
        df_1m: pd.DataFrame,
        entry_time: datetime,
        entry_price: float,
        now: datetime,
    ) -> str | None: ...


class Executor(Protocol):
    def execute_entry(
        self,
        intent: EntryIntent,
        account: AccountState,
        *,
        now: datetime | None = None,
    ) -> ExecutionOutcome: ...

    def close_position(self, symbol: str, *, now: datetime | None = None) -> ExecutionOutcome: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TradingOrchestrator:
    """Coordinates one scan cycle across the deterministic core layers."""

    def __init__(
        self,
        *,
        data: MarketDataProvider,
        strategy: StrategyEngine,
        execution: Executor,
        account: AccountProvider,
        store: DailyStateStore,
        limits: RiskLimits,
        symbols: Sequence[str],
        entry_timeframe: str = "1Min",
        trend_timeframe: str = "5Min",
        trend_timeframe_15m: str = "15Min",
        bar_limit: int = 200,
        max_entries_per_symbol_per_day: int = 10,
        max_daily_entries: int = 2,
        fallback_stop_pct: float = 0.0065,
        asset_class: str = "crypto",
        trading_capital: float | None = None,
        watchlist: Callable[[], Sequence[str]] | None = None,
        watchlist_fallback_to_static: bool = True,
        session_is_open: Callable[[datetime], bool] | None = None,
        research_advisor: ResearchAdvisor | None = None,
        research_memory: ResearchMemoryStore | None = None,
        research_evaluation: ResearchEvaluationStore | None = None,
        trade_knowledge: TradeKnowledgeStore | None = None,
        journal_path: str | None = None,
        research_brief_file: str | None = None,
        news_api_key: str = "",
        news_api_secret: str = "",
        clock: Callable[[], datetime] = _utcnow,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data = data
        self._strategy = strategy
        self._execution = execution
        self._account = account
        self._store = store
        self._limits = limits
        self._symbols = tuple(symbols)
        self._watchlist = watchlist
        self._watchlist_fallback_to_static = watchlist_fallback_to_static
        self._session_is_open = session_is_open
        self._research = research_advisor
        self._memory = research_memory
        self._evaluation = research_evaluation
        self._trade_knowledge = trade_knowledge
        self._journal_path = journal_path
        self._research_brief_file = research_brief_file
        self._news_api_key = news_api_key
        self._news_api_secret = news_api_secret
        self._entry_tf = entry_timeframe
        self._trend_tf = trend_timeframe
        self._trend_tf_15m = trend_timeframe_15m
        self._bar_limit = bar_limit
        self._max_entries = max_entries_per_symbol_per_day
        self._max_daily_entries = max_daily_entries
        self._fallback_stop_pct = fallback_stop_pct
        self._asset_class = asset_class
        self._trading_capital = trading_capital if trading_capital and trading_capital > 0 else None
        self._clock = clock
        self._log = logger or logging.getLogger("my_trade.monitoring")
        self._state: DailyState = self._store.load() or DailyState.empty()
        self._prev_positions: dict[str, Position] = {}

    def _sync_trade_knowledge(self) -> int:
        if self._trade_knowledge is None or not self._journal_path:
            return 0
        thesis = self._memory.thesis_cache if self._memory is not None else None
        return self._trade_knowledge.sync_from_journal(
            self._journal_path,
            thesis_by_symbol=thesis,
        )

    def _record_knowledge_reflection(self, reflection: object) -> None:
        if self._trade_knowledge is None:
            return
        from my_trade.research.models import ClosedTradeReflection

        if isinstance(reflection, ClosedTradeReflection):
            self._trade_knowledge.record_from_reflection(reflection)

    @property
    def state(self) -> DailyState:
        return self._state

    def _persist(self, state: DailyState) -> None:
        self._state = state
        self._store.save(state)

    def _get_bars(self, symbol: str, timeframe: str) -> pd.DataFrame:
        return self._data.get_bars(symbol, timeframe, self._bar_limit)

    def _active_symbols(self) -> tuple[str, ...]:
        """Symbols to scan this cycle.

        When a dynamic ``watchlist`` (e.g. the screener) is configured we use it,
        but fail safe to the statically configured symbols if it errors or is
        empty — the screener narrowing the universe must never *halt* trading.
        """
        if self._watchlist is None:
            return self._symbols
        try:
            selected = tuple(self._watchlist())
        except Exception as exc:
            self._log.warning("watchlist failed, using static symbols: %s", exc)
            return self._symbols
        if not selected:
            if not self._watchlist_fallback_to_static:
                self._log.debug("watchlist empty; no static fallback configured")
                return ()
            self._log.debug("watchlist empty; falling back to static symbols")
            return self._symbols
        return selected

    def run_cycle(self, now: datetime | None = None) -> CycleResult:
        when = now or self._clock()
        actions: list[CycleAction] = []

        try:
            snapshot = self._account.get_snapshot()
        except Exception as exc:  # fail safe: no account state => do nothing
            self._log.error("account snapshot failed: %s", exc)
            return CycleResult(
                timestamp=when,
                equity=0.0,
                day_pnl=0.0,
                peak_equity=self._state.peak_equity,
                open_positions=0,
                actions=(CycleAction(ActionKind.ERROR, detail=str(exc)),),
            )

        # Daily rollover + peak tracking, persisted before any decision.
        prev_day = self._state.trading_day
        today = when.date()
        if (
            self._trade_knowledge is not None
            and prev_day != today
            and prev_day != date(1970, 1, 1)
        ):
            pre_rollover = build_account_state(
                snapshot,
                self._state,
                self._fallback_stop_pct,
                trading_capital=self._trading_capital,
            )
            self._sync_trade_knowledge()
            self._trade_knowledge.finalize_trading_day(
                prev_day,
                equity=pre_rollover.equity,
                day_pnl=pre_rollover.realized_day_pnl,
            )

        state = rollover_if_new_day(
            self._state,
            when.date(),
            snapshot.equity,
            trading_capital=self._trading_capital,
        )
        if self._trading_capital and state.broker_sod_equity <= 0:
            state = replace(
                state,
                broker_sod_equity=snapshot.equity,
                start_of_day_equity=self._trading_capital,
            )
        account_state = build_account_state(
            snapshot,
            state,
            self._fallback_stop_pct,
            trading_capital=self._trading_capital,
        )
        # Persist peak on the same scale as account_state (virtual when TRADING_CAPITAL set).
        state = replace(state, peak_equity=account_state.peak_equity)
        self._persist(state)
        self._sync_trade_knowledge()
        day_pnl = account_state.realized_day_pnl

        # (1) Manage exits first — always, even if entries are halted.
        actions.extend(self._manage_exits(snapshot, when))
        actions.extend(self._learn_from_broker_closes(snapshot, when))

        # (2) Halt gate for NEW entries.
        halt_reason = self._halt_reason(account_state)
        if halt_reason is not None:
            self._log.warning("entries halted: %s", halt_reason.value)
            actions.append(CycleAction(ActionKind.HALT, detail=halt_reason.value))
            actions.extend(
                self._learn_from_session_halt(
                    halt_reason=halt_reason.value,
                    account_state=account_state,
                    when=when,
                )
            )
            return CycleResult(
                timestamp=when,
                equity=account_state.equity,
                day_pnl=day_pnl,
                peak_equity=account_state.peak_equity,
                open_positions=account_state.open_positions,
                halted=True,
                halt_reason=halt_reason,
                actions=tuple(actions),
            )

        # (3) Claude research (advisory) — runs even when the session is closed so
        # proposals and memory keep updating; entries remain session-gated below.
        open_symbols = {normalize_symbol(p.symbol) for p in snapshot.positions}
        research_actions, research_proposal = self._run_research(
            snapshot, account_state, when, open_symbols
        )
        actions.extend(research_actions)

        # (4) Session gate — never open NEW entries while the market is closed
        # (exits above still run; bracket legs remain live at the broker).
        if self._session_is_open is not None and not self._session_is_open(when):
            self._log.info("market closed; skipping new entries this cycle")
            actions.append(CycleAction(ActionKind.SESSION_CLOSED))
            return CycleResult(
                timestamp=when,
                equity=account_state.equity,
                day_pnl=day_pnl,
                peak_equity=account_state.peak_equity,
                open_positions=account_state.open_positions,
                actions=tuple(actions),
            )

        # (5) Entries.
        actions.extend(
            self._scan_entries(open_symbols, account_state, when, research_proposal)
        )

        return CycleResult(
            timestamp=when,
            equity=account_state.equity,
            day_pnl=day_pnl,
            peak_equity=account_state.peak_equity,
            open_positions=account_state.open_positions,
            actions=tuple(actions),
        )

    def _halt_reason(self, account_state: AccountState) -> HaltReason | None:
        if is_circuit_breaker_tripped(account_state, self._limits):
            return HaltReason.CIRCUIT_BREAKER
        if is_daily_loss_limit_hit(account_state, self._limits):
            return HaltReason.DAILY_LOSS_LIMIT
        if is_daily_profit_target_hit(account_state, self._limits):
            return HaltReason.DAILY_PROFIT_TARGET
        return None

    def _manage_exits(self, snapshot: AccountSnapshot, when: datetime) -> list[CycleAction]:
        actions: list[CycleAction] = []
        for pos in snapshot.positions:
            bars = self._get_bars(pos.symbol, self._entry_tf)
            entry_time = entry_time_for(self._state, pos.symbol) or when
            reason = self._strategy.detect_exit(
                bars, entry_time, pos.avg_entry_price, when
            )
            if reason is None:
                continue
            outcome = self._execution.close_position(pos.symbol, now=when)
            if outcome.submitted:
                self._persist(clear_position(self._state, pos.symbol))
                self._log.info("EXIT %s (%s)", pos.symbol, reason)
                actions.append(CycleAction(ActionKind.EXIT_SUBMITTED, pos.symbol, reason))
                if self._memory is not None:
                    reflection = self._memory.record_close(
                        symbol=pos.symbol,
                        exit_reason=reason,
                        entry_price=pos.avg_entry_price,
                        qty=pos.qty,
                        unrealized_pl=pos.unrealized_pl,
                        closed_at=when,
                    )
                    if self._evaluation is not None:
                        self._evaluation.record_outcome(
                            symbol=pos.symbol,
                            outcome=reflection.outcome,
                            pnl_estimate=reflection.pnl_estimate,
                            when=when,
                        )
                    self._record_knowledge_reflection(reflection)
                    detail = reflection.llm_summary or reflection.summary
                    self._log.info(
                        "CLAUDE reflection %s (%s) | %s",
                        pos.symbol,
                        reflection.outcome,
                        detail[:160],
                    )
                    actions.append(
                        CycleAction(
                            ActionKind.RESEARCH_REFLECTION,
                            pos.symbol,
                            detail,
                        )
                    )
            else:
                self._log.error("exit failed for %s: %s", pos.symbol, outcome.detail)
                actions.append(
                    CycleAction(ActionKind.EXIT_FAILED, pos.symbol, outcome.detail)
                )
        return actions

    def _learn_from_broker_closes(
        self, snapshot: AccountSnapshot, when: datetime
    ) -> list[CycleAction]:
        """Detect positions that disappeared at the broker without a bot exit_submitted."""
        actions: list[CycleAction] = []
        current = {normalize_symbol(p.symbol): p for p in snapshot.positions}
        for sym, prev in self._prev_positions.items():
            if sym in current:
                continue
            if sym in self._state.position_stops or self._state.entries_for(sym) > 0:
                self._persist(clear_position(self._state, sym))
            entry_count = max(self._state.entries_for(sym), 1)
            if self._memory is None:
                continue
            ref = self._memory.record_broker_close(
                symbol=sym,
                entry_price=prev.avg_entry_price,
                qty=prev.qty,
                pnl_estimate=prev.unrealized_pl,
                closed_at=when,
                entry_count=entry_count,
            )
            if ref is None:
                continue
            if self._evaluation is not None:
                self._evaluation.record_outcome(
                    symbol=sym,
                    outcome=ref.outcome,
                    pnl_estimate=ref.pnl_estimate,
                    when=when,
                )
            self._record_knowledge_reflection(ref)
            detail = ref.llm_summary or ref.summary
            self._log.info(
                "loss lesson %s (%s) | %s",
                sym,
                ref.outcome,
                detail[:160],
            )
            actions.append(
                CycleAction(ActionKind.RESEARCH_REFLECTION, sym, detail)
            )
        self._prev_positions = current
        return actions

    def _learn_from_session_halt(
        self,
        *,
        halt_reason: str,
        account_state: AccountState,
        when: datetime,
    ) -> list[CycleAction]:
        actions: list[CycleAction] = []
        if self._state.halt_lesson_logged or self._memory is None:
            return actions
        ref = self._memory.record_session_halt(
            halt_reason=halt_reason,
            day_pnl=account_state.realized_day_pnl,
            equity=account_state.equity,
            closed_at=when,
        )
        self._persist(mark_halt_lesson_logged(self._state))
        if ref is None:
            return actions
        detail = ref.llm_summary or ref.summary
        self._log.info("session halt lesson | %s", detail[:200])
        actions.append(CycleAction(ActionKind.RESEARCH_REFLECTION, "SESSION", detail))
        return actions

    def _open_risk_dollars(self, snapshot: AccountSnapshot) -> float:
        total = 0.0
        for pos in snapshot.positions:
            sym = normalize_symbol(pos.symbol)
            stop = self._state.position_stops.get(sym)
            if stop is None:
                stop = pos.avg_entry_price * (1.0 - self._fallback_stop_pct)
            risk_per_share = pos.avg_entry_price - stop
            if risk_per_share > 0:
                total += risk_per_share * pos.qty
        return total

    def _claude_long(self, symbol: str, proposal: ClaudeProposal | None) -> bool:
        if self._research is None or proposal is None or proposal.skipped:
            return False
        return symbol.upper() in self._research.approved_symbols(proposal)

    def _run_research(
        self,
        snapshot: AccountSnapshot,
        account_state: AccountState,
        when: datetime,
        open_symbols: set[str],
    ) -> tuple[list[CycleAction], object | None]:
        if self._research is None or not self._research.is_active_for(self._asset_class):
            if self._research is not None and not self._research.is_active_for(
                self._asset_class
            ):
                self._log.debug(
                    "research inactive (asset_class=%s, equities_only=%s)",
                    self._asset_class,
                    self._research.config.equities_only,
                )
            return [], None
        session_open = True
        if self._session_is_open is not None:
            session_open = self._session_is_open(when)
        if self._research.config.market_hours_only and not session_open:
            self._log.debug("research skipped (market closed, market_hours_only=true)")
            return [], None
        candidates = self._active_symbols()
        if not candidates:
            return [], None
        sym_set = frozenset(normalize_symbol(s) for s in candidates)
        recent_reflections = ()
        performance = None
        if self._memory is not None:
            if self._journal_path:
                self._memory.enrich_from_journal(
                    self._journal_path, candidate_symbols=candidates
                )
            recent_reflections = self._memory.recent_reflections(
                limit=10, symbols=sym_set
            )
            performance = self._memory.performance_summary(symbols=sym_set)
        comparison_summary = None
        if self._evaluation is not None:
            comparison_summary = self._evaluation.summary()
        from my_trade.research.brief import load_brief
        from my_trade.research.context import build_research_context

        daily_brief = None
        if self._research_brief_file:
            daily_brief = load_brief(self._research_brief_file)

        trade_knowledge: tuple[dict[str, object], ...] = ()
        if self._trade_knowledge is not None:
            self._sync_trade_knowledge()
            trade_knowledge = tuple(
                self._trade_knowledge.recent_for_prompt(
                    symbols=candidates,
                    limit=25,
                )
            )

        from my_trade.research.news import fetch_recent_news
        from my_trade.research.technical import gather_technical_scans

        technical_scans = gather_technical_scans(
            symbols=tuple(candidates),
            strategy=self._strategy,
            get_bars=self._get_bars,
            entry_tf=self._entry_tf,
            trend_tf=self._trend_tf,
            trend_tf_15m=self._trend_tf_15m,
            when=when,
        )
        recent_news: tuple[dict[str, object], ...] = ()
        if self._asset_class == "equities" and self._news_api_key and self._news_api_secret:
            recent_news = fetch_recent_news(
                candidates,
                api_key=self._news_api_key,
                api_secret=self._news_api_secret,
                as_of=when,
            )

        context = build_research_context(
            snapshot=snapshot,
            candidate_symbols=candidates,
            asset_class=self._asset_class,
            session_open=session_open,
            as_of=when,
            equity=account_state.equity,
            day_pnl=account_state.realized_day_pnl,
            peak_equity=account_state.peak_equity,
            open_risk_dollars=self._open_risk_dollars(snapshot),
            recent_reflections=recent_reflections,
            performance=performance,
            comparison_summary=comparison_summary,
            daily_brief=daily_brief,
            trade_knowledge=trade_knowledge,
            technical_scans=technical_scans,
            recent_news=recent_news,
        )
        result = self._research.propose(context, when=when)
        proposal = result.proposal
        actions: list[CycleAction] = []
        provider = proposal.provider or "research"
        if proposal.skipped:
            reason = proposal.skip_reason or "skipped"
            self._log.info("research skipped (%s): %s", provider, reason)
            # Routine interval / budget waits are expected — keep them out of the activity feed.
            if not reason.startswith("rate limited (") and not reason.startswith(
                "daily budget exhausted"
            ):
                actions.append(CycleAction(ActionKind.RESEARCH_SKIPPED, detail=reason))
            return actions, proposal
        if self._memory is not None:
            self._memory.note_proposals(proposal.ideas)
        self._log.info(
            "research (%s/%s) | %d ideas (%d long) | %s",
            provider,
            proposal.model or "?",
            len(proposal.ideas),
            len(proposal.long_ideas),
            (proposal.summary or "no summary")[:160],
        )
        for idea in proposal.ideas:
            detail = (
                f"[{provider}] {idea.action.value} conf={idea.confidence:.2f} "
                f"{idea.instrument.value} {idea.time_horizon}: {idea.thesis[:240]}"
            )
            actions.append(
                CycleAction(ActionKind.RESEARCH_PROPOSAL, idea.symbol, detail)
            )
            if idea.action.value == "long":
                self._log.info(
                    "research idea %s long conf=%.2f (%s) | %s",
                    idea.symbol,
                    idea.confidence,
                    provider,
                    idea.thesis[:120],
                )
        return actions, proposal

    def _scan_entries(
        self,
        open_symbols: set[str],
        account_state: AccountState,
        when: datetime,
        research_proposal: object | None = None,
    ) -> list[CycleAction]:
        actions: list[CycleAction] = []
        strategy_signals: dict[str, bool] = {}
        proposal = (
            research_proposal
            if isinstance(research_proposal, ClaudeProposal)
            else None
        )
        if self._state.total_entries_today() >= self._max_daily_entries:
            actions.append(
                CycleAction(
                    ActionKind.SKIP_MAX_ENTRIES,
                    "",
                    f"daily_entries={self._state.total_entries_today()} max={self._max_daily_entries}",
                )
            )
            return actions
        for symbol in self._active_symbols():
            sym = normalize_symbol(symbol)
            if sym not in open_symbols and sym in self._state.position_stops:
                self._persist(clear_position(self._state, sym))
                self._log.info(
                    "reconciled stale position state for %s (broker flat)", sym
                )
            if sym in open_symbols:
                actions.append(CycleAction(ActionKind.SKIP_OPEN_POSITION, symbol))
                continue
            if account_state.open_positions >= self._limits.max_concurrent_positions:
                actions.append(
                    CycleAction(
                        ActionKind.ENTRY_REJECTED,
                        symbol,
                        "risk rejected: max_positions",
                    )
                )
                continue
            if self._state.entries_for(symbol) >= self._max_entries:
                actions.append(
                    CycleAction(
                        ActionKind.SKIP_MAX_ENTRIES,
                        symbol,
                        f"entries_today={self._state.entries_for(symbol)} max={self._max_entries}",
                    )
                )
                continue
            sticky = (
                self._memory.stance_for_symbol(sym)
                if self._memory is not None
                else None
            )
            if self._research is not None and proposal is not None:
                veto = (
                    self._research.entry_veto_reason(
                        symbol, proposal, sticky_idea=sticky
                    )
                    if hasattr(self._research, "entry_veto_reason")
                    else None
                )
                if veto is None and not self._research.allows_entry(
                    symbol, proposal, sticky_idea=sticky
                ):
                    veto = "research blocked entry"
                if veto is not None:
                    actions.append(
                        CycleAction(ActionKind.RESEARCH_NOT_APPROVED, symbol, veto)
                    )
                    continue

            signal, evaluation = self._strategy.detect_entry(
                symbol,
                self._get_bars(symbol, self._entry_tf),
                self._get_bars(symbol, self._trend_tf),
                self._get_bars(symbol, self._trend_tf_15m),
                when,
            )
            strategy_signals[sym] = signal is not None
            if signal is None:
                self._log.debug("no signal %s: %s", symbol, evaluation.summary)
                actions.append(CycleAction(ActionKind.NO_SIGNAL, symbol, evaluation.summary))
                continue

            outcome = self._execution.execute_entry(
                EntryIntent.from_signal(signal), account_state, now=when
            )
            if outcome.submitted:
                self._persist(record_entry(self._state, symbol, signal.stop_price, when))
                open_symbols.add(sym)
                account_state = replace(
                    account_state,
                    open_positions=account_state.open_positions + 1,
                )
                if self._evaluation is not None:
                    self._evaluation.record_entry(
                        symbol=symbol,
                        when=when,
                        claude_long=self._claude_long(symbol, proposal),
                        strategy_signal=True,
                    )
                self._log.info(
                    "ENTRY %s @ %.2f stop %.2f tp %.2f conf %.2f",
                    symbol,
                    signal.entry_price,
                    signal.stop_price,
                    signal.take_profit_price,
                    signal.confidence,
                )
                detail = (
                    f"entry={signal.entry_price:.2f} stop={signal.stop_price:.2f} "
                    f"tp={signal.take_profit_price:.2f} conf={signal.confidence:.2f}"
                )
                actions.append(
                    CycleAction(
                        ActionKind.ENTRY_SUBMITTED, symbol, detail, outcome.status.value
                    )
                )
                break
            else:
                self._log.info("entry rejected %s: %s", symbol, outcome.detail)
                actions.append(
                    CycleAction(
                        ActionKind.ENTRY_REJECTED,
                        symbol,
                        outcome.detail,
                        outcome.status.value,
                    )
                )
        if self._evaluation is not None and proposal is not None and not proposal.skipped:
            min_conf = self._research.config.min_confidence if self._research else 0.55
            self._evaluation.record_cycle(
                when=when,
                symbols=self._active_symbols(),
                proposal=proposal,
                strategy_signals=strategy_signals,
                min_confidence=min_conf,
            )
        return actions
