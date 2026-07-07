import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { PageHeader } from "@/components/PageHeader";
import { LiveBanner } from "@/components/LiveBanner";
import { useAccount, useConfig, useEvents, useStats, useStatus } from "@/hooks/useApi";
import { fmtPct, fmtTs, fmtUsd } from "@/lib/format";
import { AlertOctagon, ShieldAlert } from "lucide-react";

/** Config stores fractions (0.01 = 1%). */
const pct = (n: number | undefined, fallback: number) => (n ?? fallback) * 100;

export default function Risk() {
  const { data: account } = useAccount();
  const { data: cfg } = useConfig();
  const { data: stats } = useStats();
  const { data: status } = useStatus();
  const { data: events = [] } = useEvents({ limit: 500, kind: "halt" });

  const equity = account?.equity ?? 0;
  const brokerEquity = account?.broker_equity ?? null;
  const tradingCapital = cfg?.risk?.trading_capital ?? account?.trading_capital ?? 0;
  const peak = stats?.daily_state?.peak_equity ?? account?.peak_equity ?? equity;
  const dayStartEquity = stats?.daily_state?.start_of_day_equity ?? equity;
  const dayPnl = account?.day_pnl ?? 0;

  const dayLossPct = dayStartEquity ? Math.max(0, -dayPnl / dayStartEquity) * 100 : 0;
  const dayGainPct = dayStartEquity && dayPnl > 0 ? (dayPnl / dayStartEquity) * 100 : 0;
  const drawdownPct = peak ? Math.max(0, (peak - equity) / peak) * 100 : 0;

  const limits = cfg?.risk;
  const cap = tradingCapital > 0 ? tradingCapital : equity;
  const maxRiskUsd = cap * (limits?.max_risk_per_trade_pct ?? 0.02);
  const maxPosUsd = cap * (limits?.max_notional_pct ?? 0.4);
  const dailyHaltUsd = cap * (limits?.daily_loss_limit_pct ?? 0.01);
  const dailyTargetUsd = cap * (limits?.daily_profit_target_pct ?? 0.01);

  return (
    <div>
      <PageHeader title="Risk & halts" subtitle="Live exposure vs. configured limits" />
      <LiveBanner />

      {tradingCapital > 0 && (
        <div className="mb-4 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs font-data">
          <span className="text-primary font-semibold">Virtual account ${tradingCapital.toLocaleString()}</span>
          {brokerEquity != null && (
            <span className="text-muted-foreground">
              {" "}
              · Alpaca paper {fmtUsd(brokerEquity)} (sizing uses virtual balance)
            </span>
          )}
        </div>
      )}

      {status?.halted && (
        <div className="mb-4 flex items-start gap-3 px-4 py-3 rounded-lg border border-destructive/40 bg-destructive/10 text-destructive">
          <AlertOctagon className="h-5 w-5 shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold">Bot halted</div>
            <div className="text-sm">{status.halt_reason || "unknown reason"}</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <LimitCard
          title="Day P&L vs daily loss limit"
          current={dayLossPct}
          limit={pct(limits?.daily_loss_limit_pct, 0.01)}
          subLeft={`Day P&L: ${fmtUsd(dayPnl)} · halt ~${fmtUsd(-dailyHaltUsd)}`}
        />
        <LimitCard
          title="Day P&L vs profit target"
          current={dayGainPct}
          limit={pct(limits?.daily_profit_target_pct, 0.01)}
          subLeft={`Target: ${fmtUsd(dailyTargetUsd)} · locks green days`}
          gainMode
        />
        <LimitCard
          title="Drawdown from peak"
          current={drawdownPct}
          limit={pct(limits?.max_drawdown_pct, 0.15)}
          subLeft={`Peak: ${fmtUsd(peak)} · Equity: ${fmtUsd(equity)}`}
        />
        <LimitCard
          title="Open risk vs max"
          current={0}
          limit={pct(limits?.max_open_risk_pct, 0.05)}
          subLeft="Computed from open positions on backend"
        />
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-display">Growth limits</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 text-xs font-data">
            <Row label="Per trade" value={fmtPct(pct(limits?.max_risk_per_trade_pct, 0.02))} />
            <Row label="Max position" value={fmtPct(pct(limits?.max_notional_pct, 0.4))} />
            <Row label="Daily loss" value={fmtPct(pct(limits?.daily_loss_limit_pct, 0.01))} />
            <Row label="Daily target" value={fmtPct(pct(limits?.daily_profit_target_pct, 0.01))} />
            <Row label="Max drawdown" value={fmtPct(pct(limits?.max_drawdown_pct, 0.15))} />
            <Row label="Max positions" value={String(limits?.max_concurrent_positions ?? 1)} />
            <Row label="Max entries/day" value={String(limits?.max_daily_entries ?? 2)} />
            <Row label="Trading capital" value={tradingCapital > 0 ? fmtUsd(tradingCapital, 0) : "—"} />
            <Row label="~$ risk / trade" value={fmtUsd(maxRiskUsd)} />
            <Row label="~$ max position" value={fmtUsd(maxPosUsd)} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-display flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-accent-orange" /> Halt history
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {events.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground">No halts recorded.</div>
          ) : (
            <ul className="divide-y divide-border">
              {events.map((e, i) => (
                <li key={i} className="px-4 py-2 text-xs font-data flex justify-between gap-4">
                  <span className="text-muted-foreground">{fmtTs(e.ts)}</span>
                  <span className="text-accent-orange uppercase tracking-wider">{e.kind}</span>
                  <span className="flex-1 text-foreground truncate">{e.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function LimitCard({
  title,
  current,
  limit,
  subLeft,
  gainMode = false,
}: {
  title: string;
  current: number;
  limit: number;
  subLeft?: string;
  gainMode?: boolean;
}) {
  const pctOfLimit = limit ? Math.min(100, (current / limit) * 100) : 0;
  const danger = !gainMode && pctOfLimit >= 80;
  const success = gainMode && pctOfLimit >= 100;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-display">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <Progress
          value={pctOfLimit}
          className={
            success
              ? "[&>div]:bg-accent"
              : danger
                ? "[&>div]:bg-destructive"
                : "[&>div]:bg-accent"
          }
        />
        <div className="flex justify-between text-xs font-data">
          <span className="text-muted-foreground">{subLeft}</span>
          <span
            className={
              success ? "text-accent" : danger ? "text-destructive" : "text-foreground"
            }
          >
            {current.toFixed(2)}% / {limit.toFixed(2)}%
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-center px-2 py-1.5 rounded-md bg-secondary/40 border border-border">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-foreground font-semibold">{value}</span>
    </div>
  );
}
