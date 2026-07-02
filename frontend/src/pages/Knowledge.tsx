import { useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { PageHeader } from "@/components/PageHeader";
import { useTradeKnowledge } from "@/hooks/useApi";
import { fmtRelative, fmtTs, fmtUsd } from "@/lib/format";
import type { TradeKnowledgeRecord } from "@/lib/types";
import { BookOpen, TrendingDown, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

const EVENT_KINDS = [
  "all",
  "entry",
  "exit",
  "entry_rejected",
  "research_veto",
  "exit_failed",
  "research_reflection",
  "session_halt",
] as const;

const KIND_LABEL: Record<string, string> = {
  entry: "Entry",
  exit: "Exit",
  entry_rejected: "Rejected",
  research_veto: "Veto",
  exit_failed: "Exit failed",
  research_reflection: "Reflection",
  session_halt: "Halt",
};

const KIND_COLOR: Record<string, string> = {
  entry: "text-accent border-accent/30 bg-accent/10",
  exit: "text-primary border-primary/30 bg-primary/10",
  entry_rejected: "text-accent-orange border-accent-orange/30 bg-accent-orange/10",
  research_veto: "text-accent-orange border-accent-orange/30 bg-accent-orange/10",
  exit_failed: "text-destructive border-destructive/30 bg-destructive/10",
  research_reflection: "text-muted-foreground border-border bg-secondary/30",
  session_halt: "text-destructive border-destructive/30 bg-destructive/10",
};

const OUTCOME_COLOR: Record<string, string> = {
  win: "text-accent",
  loss: "text-destructive",
  flat: "text-muted-foreground",
  unknown: "text-muted-foreground",
  "n/a": "text-muted-foreground",
};

function KindBadge({ kind }: { kind: string }) {
  return (
    <span
      className={cn(
        "px-2 py-0.5 rounded-full border text-[10px] uppercase tracking-wider font-data",
        KIND_COLOR[kind] ?? "text-muted-foreground border-border bg-secondary/30",
      )}
    >
      {KIND_LABEL[kind] ?? kind}
    </span>
  );
}

function RecordCard({ record }: { record: TradeKnowledgeRecord }) {
  return (
    <Card className="border-border/80">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center gap-2 justify-between">
          <div className="flex flex-wrap items-center gap-2">
            {record.symbol && record.symbol !== "SESSION" && (
              <CardTitle className="text-base font-display">{record.symbol}</CardTitle>
            )}
            {record.symbol === "SESSION" && (
              <CardTitle className="text-base font-display text-destructive">Session</CardTitle>
            )}
            <KindBadge kind={record.event_kind} />
            {record.outcome && record.outcome !== "n/a" && (
              <span
                className={cn(
                  "text-[10px] uppercase tracking-wider font-data",
                  OUTCOME_COLOR[record.outcome] ?? "text-muted-foreground",
                )}
              >
                {record.outcome}
              </span>
            )}
            {record.research_action && (
              <span className="px-2 py-0.5 rounded-full border border-border text-[10px] uppercase font-data text-muted-foreground">
                research: {record.research_action}
              </span>
            )}
          </div>
          <span className="text-[11px] text-muted-foreground font-data">{fmtTs(record.ts)}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">What</p>
          <p className="text-foreground/90 leading-relaxed">{record.what_happened || "—"}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">How</p>
          <p className="text-foreground/80 leading-relaxed">{record.how_it_happened || "—"}</p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Why</p>
          <p className="text-foreground/80 leading-relaxed">{record.why_it_happened || "—"}</p>
        </div>
        {record.research_thesis && (
          <div className="rounded-md border border-border bg-secondary/20 p-3">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
              Research thesis
            </p>
            <p className="text-foreground/80 leading-relaxed">{record.research_thesis}</p>
          </div>
        )}
        {record.lessons.length > 0 && (
          <div className="rounded-md border border-accent-orange/20 bg-accent-orange/5 p-3 space-y-1">
            <p className="text-[10px] uppercase tracking-wider text-accent-orange mb-1">Lessons</p>
            {record.lessons.map((lesson) => (
              <p key={lesson} className="text-foreground/80 leading-relaxed text-sm">
                {lesson}
              </p>
            ))}
          </div>
        )}
        <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground font-data">
          <span>{record.trading_day}</span>
          {record.day_pnl != null && <span>Day P&L {fmtUsd(record.day_pnl)}</span>}
          {record.pnl_estimate != null && <span>Est. P&L {fmtUsd(record.pnl_estimate)}</span>}
        </div>
      </CardContent>
    </Card>
  );
}

export default function Knowledge() {
  const [symbol, setSymbol] = useState("");
  const [eventKind, setEventKind] = useState<string>("all");

  const params = useMemo(
    () => ({
      limit: 150,
      symbol: symbol.trim() || undefined,
      event_kind: eventKind === "all" ? undefined : eventKind,
    }),
    [symbol, eventKind],
  );

  const { data } = useTradeKnowledge(params);
  const stats = data?.stats;
  const summaries = data?.daily_summaries ?? [];
  const records = data?.records ?? [];

  return (
    <div>
      <PageHeader
        title="Trade Knowledge"
        subtitle="Every transaction, win, loss, and lesson — the reference log for research"
        actions={
          <div className="text-xs text-muted-foreground font-data">
            Updated {fmtRelative(data?.last_updated)}
          </div>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">
              Records
            </CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-data">{data?.record_count ?? "—"}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <TrendingUp className="h-3 w-3 text-accent" /> Wins
            </CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-data text-accent">{stats?.wins ?? "—"}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1">
              <TrendingDown className="h-3 w-3 text-destructive" /> Losses
            </CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-data text-destructive">
            {stats?.losses ?? "—"}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">
              Exits / Entries
            </CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-data">
            {stats ? `${stats.exits} / ${stats.entries}` : "—"}
          </CardContent>
        </Card>
      </div>

      {summaries.length > 0 && (
        <Card className="mb-4">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-display">Daily summaries</CardTitle>
          </CardHeader>
          <CardContent>
            <Accordion type="single" collapsible className="w-full">
              {summaries.map((day) => (
                <AccordionItem key={day.trading_day} value={day.trading_day}>
                  <AccordionTrigger className="text-sm font-data hover:no-underline">
                    <span className="flex flex-wrap items-center gap-3">
                      <span>{day.trading_day}</span>
                      <span className={day.day_pnl != null && day.day_pnl >= 0 ? "text-accent" : "text-destructive"}>
                        {day.day_pnl != null ? fmtUsd(day.day_pnl) : "—"}
                      </span>
                      <span className="text-muted-foreground text-xs">
                        {day.entries} in · {day.exits} out · {day.wins}W / {day.losses}L
                      </span>
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-3 text-sm">
                    <p className="text-foreground/80">{day.narrative}</p>
                    {day.key_lessons.length > 0 && (
                      <ul className="list-disc pl-5 space-y-1 text-foreground/70">
                        {day.key_lessons.map((lesson) => (
                          <li key={lesson}>{lesson}</li>
                        ))}
                      </ul>
                    )}
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </CardContent>
        </Card>
      )}

      <Card className="mb-4">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-display flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-accent" /> Filters
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-4">
          <div className="w-40">
            <Input
              placeholder="Symbol e.g. AAPL"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className="font-data uppercase"
            />
          </div>
          <Select value={eventKind} onValueChange={setEventKind}>
            <SelectTrigger className="w-44 font-data">
              <SelectValue placeholder="Event kind" />
            </SelectTrigger>
            <SelectContent>
              {EVENT_KINDS.map((k) => (
                <SelectItem key={k} value={k} className="font-data">
                  {k === "all" ? "All events" : KIND_LABEL[k] ?? k}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="text-xs text-muted-foreground font-data self-center">
            Showing {records.length} of {data?.record_count ?? 0}
            {stats && stats.exit_failures > 0 && (
              <span className="text-destructive ml-2">{stats.exit_failures} exit failures logged</span>
            )}
          </div>
        </CardContent>
      </Card>

      {records.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            No knowledge records yet. Start the bot or run{" "}
            <code className="text-xs bg-secondary px-1 py-0.5 rounded">python -m scripts.sync_trade_knowledge</code>{" "}
            to backfill from the journal.
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {records.map((record) => (
            <RecordCard key={record.id} record={record} />
          ))}
        </div>
      )}
    </div>
  );
}
