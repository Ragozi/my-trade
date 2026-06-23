import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/PageHeader";
import { useEvents } from "@/hooks/useApi";
import { fmtTs, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Download } from "lucide-react";
import type { ActivityEvent } from "@/lib/types";

const RESEARCH_KINDS = [
  "research_proposal",
  "research_skipped",
  "research_not_approved",
  "research_reflection",
];

const KINDS = [
  "all",
  "research_all",
  ...RESEARCH_KINDS,
  "entry_submitted",
  "entry_rejected",
  "exit_submitted",
  "halt",
  "error",
  "heartbeat",
  "daily_rollover",
];
const PAGE_SIZE = 50;

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

export default function Activity() {
  const [params, setParams] = useSearchParams();
  const [kind, setKind] = useState("all");
  const [search, setSearch] = useState("");
  const [showHeartbeat, setShowHeartbeat] = useState(false);
  const [page, setPage] = useState(0);
  const symbol = params.get("symbol") ?? "";

  const { data: events = [] } = useEvents({ limit: 1000, symbol: symbol || undefined });

  const filtered = useMemo(() => {
    return events.filter((e) => {
      if (!showHeartbeat && e.kind === "heartbeat") return false;
      if (kind === "research_all") {
        if (!RESEARCH_KINDS.includes(e.kind)) return false;
      } else if (kind !== "all" && e.kind !== kind) return false;
      if (search && !e.detail.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [events, kind, search, showHeartbeat]);

  const pageRows = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));

  const exportCsv = () => {
    const headers = ["ts", "kind", "symbol", "detail", "equity", "day_pnl"];
    const rows = filtered.map((e) =>
      [e.ts, e.kind, e.symbol ?? "", e.detail.split(`"`).join(`""`), e.equity ?? "", e.day_pnl ?? ""]
        .map((v) => `"${v}"`)
        .join(","),
    );
    const blob = new Blob([[headers.join(","), ...rows].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `my-trade-activity-${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <PageHeader
        title="Activity log"
        subtitle="Full audit trail of bot events"
        actions={
          <Button variant="outline" size="sm" className="gap-2" onClick={exportCsv}>
            <Download className="h-4 w-4" /> Export CSV
          </Button>
        }
      />

      <Card className="mb-4">
        <CardContent className="p-4 flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <Label className="text-xs">Event type</Label>
            <Select value={kind} onValueChange={(v) => { setKind(v); setPage(0); }}>
              <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
              <SelectContent>
                {KINDS.map((k) => (
                  <SelectItem key={k} value={k}>{k}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Symbol</Label>
            <Input
              value={symbol}
              onChange={(e) => {
                const v = e.target.value;
                if (v) setParams({ symbol: v }); else setParams({});
                setPage(0);
              }}
              placeholder="e.g. AAPL"
              className="w-40 font-data"
            />
          </div>
          <div className="space-y-1 flex-1 min-w-[200px]">
            <Label className="text-xs">Search detail</Label>
            <Input
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(0); }}
              placeholder="search text..."
            />
          </div>
          <div className="flex items-center gap-2 pb-2">
            <Switch checked={showHeartbeat} onCheckedChange={setShowHeartbeat} />
            <Label className="text-xs">Show heartbeats</Label>
          </div>
        </CardContent>
      </Card>

      <Card>
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
              {pageRows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-sm text-muted-foreground py-8">
                    No events match the current filters.
                  </TableCell>
                </TableRow>
              )}
              {pageRows.map((e: ActivityEvent, i) => (
                <TableRow key={`${e.ts}-${i}`}>
                  <TableCell className="font-data text-xs">{fmtTs(e.ts)}</TableCell>
                  <TableCell>
                    <span className={cn("font-data text-xs uppercase tracking-wider", KIND_COLOR[e.kind] ?? "text-foreground")}>
                      {e.kind}
                    </span>
                  </TableCell>
                  <TableCell className="font-data text-xs">{e.symbol ?? "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{e.detail}</TableCell>
                  <TableCell className="text-right font-data text-xs">{fmtUsd(e.equity)}</TableCell>
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

      <div className="flex items-center justify-between mt-3 text-xs text-muted-foreground font-data">
        <span>{filtered.length} events</span>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>Prev</Button>
          <span>Page {page + 1} / {totalPages}</span>
          <Button variant="outline" size="sm" disabled={page + 1 >= totalPages} onClick={() => setPage(p => p + 1)}>Next</Button>
        </div>
      </div>
    </div>
  );
}
