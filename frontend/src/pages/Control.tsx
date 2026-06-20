import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/PageHeader";
import { LiveBanner } from "@/components/LiveBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useBotAction, useHealth, useLogs, useStatus } from "@/hooks/useApi";
import { fmtRelative, fmtTs } from "@/lib/format";
import { Play, Power, RefreshCw, Square, Stethoscope } from "lucide-react";
import { toast } from "sonner";
import type { BotStatus } from "@/lib/types";

export default function Control() {
  const { data: status } = useStatus();
  const { data: health } = useHealth();
  const running = !!status?.bot?.running;
  const botStatus: BotStatus = status?.halted ? "HALTED" : running ? "RUNNING" : "STOPPED";
  const { data: logs } = useLogs(50, true);

  const start = useBotAction("start");
  const stop = useBotAction("stop");
  const restart = useBotAction("restart");
  const hc = useBotAction("health-check");
  const once = useBotAction("once");

  const run = async (label: string, m: { mutateAsync: () => Promise<any> }) => {
    try { const r = await m.mutateAsync(); toast.success(`${label}: ${r?.message || r?.summary || "ok"}`); }
    catch (e: any) { toast.error(`${label} failed: ${e.message}`); }
  };

  const paper = health?.paper_trading ?? true;

  return (
    <div>
      <PageHeader title="Bot control" subtitle="Operator panel for lifecycle and live logs" />
      <LiveBanner />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <Card className="lg:col-span-1 card-gradient-blue">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-display flex items-center gap-2">
              <Power className="h-4 w-4 text-primary" /> Status
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">State</span>
              <StatusBadge status={botStatus} />
            </div>
            <Row label="PID" value={status?.bot?.pid ?? "—"} />
            <Row label="Started" value={fmtTs(status?.bot?.started_at)} />
            <Row label="Last cycle" value={fmtRelative(status?.bot?.last_cycle_at)} />
            <Row label="Cycles today" value={status?.bot?.cycles_today ?? 0} />
            {status?.halted && (
              <div className="mt-2 p-2 rounded-md bg-destructive/10 border border-destructive/30 text-xs text-destructive">
                Halted: {status.halt_reason || "unknown"}
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader className="pb-2"><CardTitle className="text-sm font-display">Actions</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {running ? (
              <ConfirmDialog
                trigger={<Button variant="destructive" className="w-full gap-2"><Square className="h-4 w-4" /> Stop</Button>}
                title="Stop the bot?" destructive confirmText="Stop"
                description="Open positions remain. No new orders until restart."
                onConfirm={() => run("Stop", stop)}
              />
            ) : (
              <ConfirmDialog
                trigger={<Button className="w-full gap-2"><Play className="h-4 w-4" /> Start</Button>}
                title="Start the bot?"
                description={paper ? "Paper mode — no real money." : "LIVE MODE — real money orders will be placed."}
                destructive={!paper}
                requireTyping={paper ? undefined : "START LIVE"}
                confirmText="Start"
                onConfirm={() => run("Start", start)}
              />
            )}
            <ConfirmDialog
              trigger={<Button variant="outline" className="w-full gap-2"><RefreshCw className="h-4 w-4" /> Restart</Button>}
              title="Restart the bot?"
              description="Stops and starts the bot. Brief downtime."
              confirmText="Restart"
              onConfirm={() => run("Restart", restart)}
            />
            <Button variant="outline" className="w-full gap-2" onClick={() => run("Health check", hc)}>
              <Stethoscope className="h-4 w-4" /> Health check
            </Button>
            <ConfirmDialog
              trigger={<Button variant="outline" className="w-full gap-2 col-span-2 md:col-span-1"><RefreshCw className="h-4 w-4" /> Single cycle</Button>}
              title="Run one cycle?"
              description="Executes one scan/evaluate loop. May submit trades."
              confirmText="Run once"
              onConfirm={() => run("Single cycle", once)}
            />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2 flex flex-row items-center justify-between">
          <CardTitle className="text-sm font-display">Live logs (tail 50)</CardTitle>
          <span className="text-[10px] text-muted-foreground font-data">
            {running ? "auto-refresh 3s" : "polling paused (bot stopped)"}
          </span>
        </CardHeader>
        <CardContent>
          <pre className="bg-background border border-border rounded-md p-3 text-[11px] font-data leading-relaxed text-muted-foreground overflow-auto max-h-[460px] whitespace-pre-wrap">
            {(logs?.lines ?? []).join("\n") || "No log lines yet."}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-data">{value}</span>
    </div>
  );
}
