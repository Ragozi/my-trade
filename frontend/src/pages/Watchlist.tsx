import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/PageHeader";
import { useConfig, useWatchlist } from "@/hooks/useApi";
import { fmtNum, fmtRelative } from "@/lib/format";
import type { WatchlistKnowledge } from "@/lib/types";
import { BookOpen, Radar } from "lucide-react";

function actionClass(action: string | null | undefined): string {
  switch (action?.toLowerCase()) {
    case "long":
      return "text-accent border-accent/30 bg-accent/10";
    case "avoid":
      return "text-destructive border-destructive/30 bg-destructive/10";
    case "hold":
      return "text-accent-orange border-accent-orange/30 bg-accent-orange/10";
    default:
      return "text-muted-foreground border-border bg-secondary/30";
  }
}

function KnowledgeCard({ item }: { item: WatchlistKnowledge }) {
  return (
    <Card className="border-border/80">
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center gap-2 justify-between">
          <CardTitle className="text-base font-display">{item.symbol}</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            {item.action && (
              <span
                className={`px-2 py-0.5 rounded-full border text-[10px] uppercase tracking-wider font-data ${actionClass(item.action)}`}
              >
                {item.action}
                {item.confidence != null ? ` ${Math.round(item.confidence * 100)}%` : ""}
              </span>
            )}
            {item.instrument && item.instrument !== "shares" && (
              <span className="px-2 py-0.5 rounded-full border border-border text-[10px] uppercase font-data text-muted-foreground">
                {item.instrument}
              </span>
            )}
            {item.time_horizon && (
              <span className="px-2 py-0.5 rounded-full border border-border text-[10px] uppercase font-data text-muted-foreground">
                {item.time_horizon}
              </span>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Why we&apos;re watching</p>
          <p className="text-foreground/90 leading-relaxed">{item.why_watch || "No research context yet."}</p>
        </div>
        {item.thesis && item.thesis !== item.why_watch && (
          <div>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Thesis</p>
            <p className="text-foreground/80 leading-relaxed">{item.thesis}</p>
          </div>
        )}
        {item.recent_lesson && (
          <div className="rounded-md border border-accent-orange/20 bg-accent-orange/5 p-3">
            <p className="text-[10px] uppercase tracking-wider text-accent-orange mb-1">Recent lesson</p>
            <p className="text-foreground/80 leading-relaxed">{item.recent_lesson}</p>
          </div>
        )}
        <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground font-data">
          {item.provider && <span>Research: {item.provider}</span>}
          {item.updated_at && <span>Updated {fmtRelative(item.updated_at)}</span>}
        </div>
      </CardContent>
    </Card>
  );
}

export default function Watchlist() {
  const { data: wl } = useWatchlist();
  const { data: cfg } = useConfig();
  const screenerOn = cfg?.screener?.enabled;
  const ranked = wl?.ranked ?? [];
  const knowledge = wl?.knowledge ?? [];
  const staticSymbols = cfg?.symbols ?? [];
  const displaySymbols = ranked.length ? ranked.map((r) => r.symbol) : staticSymbols;

  return (
    <div>
      <PageHeader
        title="Watchlist"
        subtitle="What the bot is considering — and why"
        actions={
          <div className="text-xs text-muted-foreground font-data">
            Refreshed {fmtRelative(wl?.refreshed_at)}
          </div>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">Source</CardTitle></CardHeader>
          <CardContent className="text-sm font-data">{wl?.universe_source ?? (screenerOn ? "screener" : "static")}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">Screener</CardTitle></CardHeader>
          <CardContent className="text-sm font-data">{screenerOn ? "ENABLED" : "DISABLED"}</CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">Symbols</CardTitle></CardHeader>
          <CardContent className="text-sm font-data">{displaySymbols.length}</CardContent>
        </Card>
      </div>

      <Card className="mb-4">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-display flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-accent" /> Knowledge
          </CardTitle>
        </CardHeader>
        <CardContent>
          {knowledge.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Research context will appear here after the bot runs a research cycle.
            </p>
          ) : (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              {knowledge.map((item) => (
                <KnowledgeCard key={item.symbol} item={item} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-display flex items-center gap-2">
            <Radar className="h-4 w-4 text-primary" /> Ranked candidates
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {ranked.length === 0 ? (
            <div className="p-6">
              {staticSymbols.length === 0 ? (
                <p className="text-sm text-muted-foreground">No symbols configured.</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {staticSymbols.map((s) => (
                    <span key={s} className="px-2 py-1 rounded-md bg-secondary/50 border border-border text-xs font-data">
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>#</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead className="text-right">ATR %</TableHead>
                  <TableHead className="text-right">$ Volume</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ranked.map((r, i) => (
                  <TableRow key={r.symbol}>
                    <TableCell className="font-data text-xs text-muted-foreground">{i + 1}</TableCell>
                    <TableCell className="font-data font-semibold">{r.symbol}</TableCell>
                    <TableCell className="text-right font-data">{r.atr_pct.toFixed(2)}%</TableCell>
                    <TableCell className="text-right font-data">${fmtNum(r.dollar_volume, 0)}</TableCell>
                    <TableCell className="text-right font-data text-primary">{r.score.toFixed(3)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
