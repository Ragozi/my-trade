import { useMemo } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Briefcase,
  CircleDollarSign,
  Gauge,
  Play,
  RefreshCw,
  Square,
  Stethoscope,
  TimerReset,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/components/PageHeader";
import { LiveBanner } from "@/components/LiveBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  useAccount,
  useBotAction,
  useEvents,
  useHealth,
  useStats,
  useStatus,
} from "@/hooks/useApi";
import { fmtNum, fmtPct, fmtRelative, fmtTs, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ActivityEvent, BotStatus } from "@/lib/types";

const KIND_COLOR: Record<string, string> = {
  entry_submitted: "text-accent",
  entry_rejected: "text-accent-orange",
  exit_submitted: "text-destructive",
  halt: "text-destructive",
  error: "text-destructive",
  heartbeat: "text-muted-foreground",
  daily_rollover: "text-primary",
  research_proposal: "text-primary",
  research_skipped: "text-muted-foreground",
  research_not_approved: "text-accent-orange",
  research_reflection: "text-accent",
};

export default function Dashboard() {
  const { data: status } = useStatus();
  const { data: account } = useAccount();
  const { data: stats } = useStats();
  const { data: health } = useHealth();
  const { data: events } = useEvents({ limit: 200 });

  const botStatus: BotStatus = status?.halted
    ? "HALTED"
    : status?.bot?.running
    ? "RUNNING"
    : "STOPPED";

  const dayPnl = account?.day_pnl ?? stats?.latest_equity?.day_pnl ?? 0;
  const equity = account?.equity ?? stats?.latest_equity?.equity ?? 0;
  const tradingCapital = account?.trading_capital ?? null;
  const brokerEquity = account?.broker_equity ?? null;
  const dayPnlPct = equity ? (dayPnl / Math.max(equity - dayPnl, 1)) * 100 : 0;

  const equityCurve = useMemo(() => {
    if (!events) return [] as { t: number; equity: number }[];
    return events
      .filter((e) => e.equity != null && e.kind === "heartbeat")
      .slice(-200)
      .map((e) => ({ t: new Date(e.ts).getTime(), equity: e.equity as number }));
  }, [events]);

  const recent = (events ?? []).slice(0, 20);

  const startMut = useBotAction("start");
  const stopMut = useBotAction("stop");
  const healthMut = useBotAction("health-check");
  const onceMut = useBotAction("once");

  const runAction = async (
    label: string,
    mut: { mutateAsync: () => Promise<any> },
  ) => {
    try {
      const r = await mut.mutateAsync();
      toast.success(`${label}: ${r?.message || r?.summary || "ok"}`);
    } catch (e: any) {
      toast.error(`${label} failed: ${e.message}`);
    }
  };

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Real-time bot health, P&L, and recent activity"
        actions={
          <div className="flex items-center gap-2">
            <ConfirmDialog
              trigger={
                <Button variant="outline" size="sm" className="gap-2">
                  <Stethoscope className="h-4 w-4" /> Health check
                </Button>
              }
              title="Run health check?"
              description="Pings the backend to verify account, data, and execution connectivity. Read-only."
              confirmText="Run check"
              onConfirm={() => runAction("Health check", healthMut)}
            />
            <ConfirmDialog
              trigger={
                <Button variant="outline" size="sm" className="gap-2">
                  <RefreshCw className="h-4 w-4" /> Single cycle
                </Button>
              }
              title="Run a single cycle?"
              description="Executes one scan/evaluate loop without starting the long-running bot. Trades may be submitted if signals trigger."
              confirmText="Run once"
              onConfirm={() => runAction("Single cycle", onceMut)}
            />
            {botStatus === "RUNNING" ? (
              <ConfirmDialog
                trigger={
                  <Button variant="destructive" size="sm" className="gap-2">
                    <Square className="h-4 w-4" /> Stop bot
                  </Button>
                }
                title="Stop the bot?"
                description="Open positions will remain. The bot will not submit new orders until restarted."
                destructive
                confirmText="Stop bot"
                onConfirm={() => runAction("Stop", stopMut)}
              />
            ) : (
              <ConfirmDialog
                trigger={
                  <Button size="sm" className="gap-2">
                    <Play className="h-4 w-4" /> Start bot
                  </Button>
                }
                title="Start the bot?"
                description={
                  health?.paper_trading
                    ? "Starts the bot in PAPER mode. No real money at risk."
                    : "LIVE MODE — real money orders will be placed automatically."
                }
                destructive={!health?.paper_trading}
                requireTyping={health?.paper_trading ? undefined : "START LIVE"}
                confirmText="Start bot"
                onConfirm={() => runAction("Start", startMut)}
              />
            )}
          </div>
        }
      />

      <LiveBanner />

      {tradingCapital != null && tradingCapital > 0 && (
        <div className="mb-4 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs font-data text-primary">
          Slow &amp; steady mode · virtual capital {fmtUsd(tradingCapital)}
          {brokerEquity != null && (
            <span className="text-muted-foreground">
              {" "}
              · Alpaca paper {fmtUsd(brokerEquity)}
            </span>
          )}
        </div>
      )}

      {status?.research?.enabled && (
        <div
          className={cn(
            "mb-4 rounded-md border px-3 py-2 text-xs font-data",
            status.research.active
              ? "border-primary/40 bg-primary/5 text-primary"
              : "border-accent-orange/40 bg-accent-orange/5 text-accent-orange",
          )}
        >
          Research{" "}
          {status.research.active ? "ACTIVE (advisory)" : "ENABLED but inactive"}
          {status.research.active && (
            <>
              {status.research.tier_mode ? ` · ${status.research.tier_mode}` : ""}
              {status.research.workhorse_provider
                ? ` · ${status.research.workhorse_provider}${status.research.workhorse_model ? `/${status.research.workhorse_model}` : ""}`
                : ""}
              {status.research.claude_enabled && status.research.claude_model
                ? ` · claude/${status.research.claude_model}`
                : ""}
            </>
          )}
          {!status.research.active && status.session?.asset_class !== "equities"
            ? " — switch ASSET_CLASS=equities to activate"
            : ""}
        </div>
      )}

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-4">
        <KpiCard
          label={tradingCapital ? "Trading equity" : "Equity"}
          value={fmtUsd(equity)}
          sub={
            tradingCapital && brokerEquity
              ? `Paper ${fmtUsd(brokerEquity)}`
              : undefined
          }
          icon={<CircleDollarSign className="h-4 w-4 text-primary" />}
          tone="primary"
        />
        <KpiCard
          label="Day P&L"
          value={fmtUsd(dayPnl)}
          sub={fmtPct(dayPnlPct)}
          icon={
            dayPnl >= 0 ? (
              <ArrowUpRight className="h-4 w-4 text-accent" />
            ) : (
              <ArrowDownRight className="h-4 w-4 text-destructive" />
            )
          }
          tone={dayPnl >= 0 ? "green" : "red"}
        />
        <KpiCard
          label="Open positions"
          value={fmtNum(account?.open_positions ?? 0)}
          icon={<Briefcase className="h-4 w-4 text-accent-purple" />}
          tone="purple"
        />
        <KpiCard
          label="Bot status"
          value={<StatusBadge status={botStatus} />}
          icon={<Activity className="h-4 w-4 text-accent" />}
          tone="green"
        />
        <KpiCard
          label="Asset class"
          value={(health?.asset_class ?? "—").toUpperCase()}
          icon={<Gauge className="h-4 w-4 text-accent-orange" />}
          tone="orange"
        />
        <KpiCard
          label="Session"
          value={status?.session?.open ? "OPEN" : "CLOSED"}
          icon={<TimerReset className="h-4 w-4 text-primary" />}
          tone="primary"
        />
      </div>

      {/* Second row: stats + risk summary */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <Card className="lg:col-span-2 card-gradient-blue">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-display flex items-center justify-between">
              <span>Equity curve</span>
              <span className="text-xs font-data text-muted-foreground">
                {equityCurve.length} heartbeats
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="h-48">
            {equityCurve.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={equityCurve}>
                  <defs>
                    <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="hsl(217 100% 65%)" stopOpacity={0.5} />
                      <stop offset="95%" stopColor="hsl(217 100% 65%)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis
                    dataKey="t"
                    tickFormatter={(t) => new Date(t).toLocaleTimeString()}
                    stroke="hsl(245 15% 60%)"
                    fontSize={10}
                  />
                  <YAxis
                    stroke="hsl(245 15% 60%)"
                    fontSize={10}
                    domain={["auto", "auto"]}
                    tickFormatter={(v) => `$${Math.round(v).toLocaleString()}`}
                  />
                  <ChartTooltip
                    contentStyle={{
                      background: "hsl(240 18% 7%)",
                      border: "1px solid hsl(240 10% 12%)",
                      borderRadius: 8,
                      fontFamily: "JetBrains Mono",
                      fontSize: 12,
                    }}
                    labelFormatter={(t) => new Date(t as number).toLocaleString()}
                    formatter={(v: number) => fmtUsd(v)}
                  />
                  <Area
                    type="monotone"
                    dataKey="equity"
                    stroke="hsl(217 100% 65%)"
                    fill="url(#eq)"
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <EmptyHint text="No equity heartbeats yet. Once the bot runs a cycle, the curve will populate." />
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-display">Today</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-3 text-sm font-data">
              <MiniStat label="Entries" value={stats?.today?.entries ?? 0} tone="green" />
              <MiniStat label="Exits" value={stats?.today?.exits ?? 0} tone="red" />
              <MiniStat
                label="Research ideas"
                value={stats?.today?.research_proposals ?? 0}
                tone="green"
              />
              <MiniStat
                label="Reflections"
                value={stats?.today?.research_reflections ?? 0}
                tone="purple"
              />
              <MiniStat label="Halts" value={stats?.today?.halts ?? 0} tone="orange" />
              <MiniStat label="Errors" value={stats?.today?.errors ?? 0} tone="red" />
              <MiniStat
                label="Peak equity"
                value={fmtUsd(stats?.daily_state?.peak_equity ?? account?.peak_equity)}
                tone="primary"
                span
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-display">Risk limits</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2 text-xs font-data">
              <RiskChip label="R1 / trade" value="2%" />
              <RiskChip label="R2 open" value="7%" />
              <RiskChip label="R3 daily" value="5%" />
              <RiskChip label="R4 drawdown" value="15%" />
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Recent activity */}
      <Card>
        <CardHeader className="pb-2 flex flex-row items-center justify-between">
          <CardTitle className="text-sm font-display">Recent activity</CardTitle>
          <span className="text-xs text-muted-foreground font-data">
            {recent.length} of {events?.length ?? 0}
          </span>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[180px]">Time (UTC)</TableHead>
                <TableHead className="w-[160px]">Event</TableHead>
                <TableHead className="w-[120px]">Symbol</TableHead>
                <TableHead>Detail</TableHead>
                <TableHead className="text-right w-[120px]">Equity</TableHead>
                <TableHead className="text-right w-[120px]">Day P&L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recent.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-sm text-muted-foreground py-8">
                    No events yet.
                  </TableCell>
                </TableRow>
              )}
              {recent.map((e: ActivityEvent, i) => (
                <TableRow key={`${e.ts}-${i}`}>
                  <TableCell className="font-data text-xs">{fmtTs(e.ts)}</TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        "font-data text-xs uppercase tracking-wider",
                        KIND_COLOR[e.kind] ?? "text-foreground",
                      )}
                    >
                      {e.kind}
                    </span>
                  </TableCell>
                  <TableCell className="font-data text-xs">{e.symbol ?? "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground truncate max-w-[420px]">
                    {e.detail}
                  </TableCell>
                  <TableCell className="text-right font-data text-xs">
                    {fmtUsd(e.equity)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "text-right font-data text-xs",
                      (e.day_pnl ?? 0) > 0 && "text-accent",
                      (e.day_pnl ?? 0) < 0 && "text-destructive",
                    )}
                  >
                    {fmtUsd(e.day_pnl)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <p className="text-[10px] text-muted-foreground mt-4 font-data">
        Last updated {fmtRelative(status?.bot?.last_cycle_at ?? null)} · auto-refresh every 5–10s
      </p>
    </div>
  );
}

function KpiCard({
  label,
  value,
  sub,
  icon,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
  icon: React.ReactNode;
  tone?: "primary" | "green" | "red" | "purple" | "orange";
}) {
  const toneClass =
    tone === "green"
      ? "card-gradient-green"
      : tone === "red"
      ? "card-gradient-red"
      : tone === "purple"
      ? "card-gradient-purple"
      : tone === "orange"
      ? "card-gradient-orange"
      : "card-gradient-blue";
  return (
    <Card className={cn(toneClass, "hover-lift")}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">
            {label}
          </span>
          {icon}
        </div>
        <div className="text-xl font-semibold font-data text-foreground">{value}</div>
        {sub && <div className="text-xs text-muted-foreground font-data mt-1">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function MiniStat({
  label,
  value,
  tone,
  span,
}: {
  label: string;
  value: React.ReactNode;
  tone?: "green" | "red" | "orange" | "primary";
  span?: boolean;
}) {
  const color =
    tone === "green"
      ? "text-accent"
      : tone === "red"
      ? "text-destructive"
      : tone === "orange"
      ? "text-accent-orange"
      : "text-primary";
  return (
    <div className={cn("flex justify-between items-baseline", span && "col-span-2")}>
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={cn("font-data", color)}>{value}</span>
    </div>
  );
}

function RiskChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-center px-2 py-1.5 rounded-md bg-secondary/40 border border-border">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-foreground font-semibold">{value}</span>
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return (
    <div className="h-full flex items-center justify-center text-xs text-muted-foreground text-center px-6">
      {text}
    </div>
  );
}
