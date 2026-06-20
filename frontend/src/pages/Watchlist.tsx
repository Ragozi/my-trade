import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/PageHeader";
import { useConfig, useWatchlist } from "@/hooks/useApi";
import { fmtNum, fmtRelative } from "@/lib/format";
import { Radar } from "lucide-react";

export default function Watchlist() {
  const { data: wl } = useWatchlist();
  const { data: cfg } = useConfig();
  const screenerOn = cfg?.screener?.enabled;
  const ranked = wl?.ranked ?? [];
  const staticSymbols = cfg?.symbols ?? [];

  return (
    <div>
      <PageHeader
        title="Watchlist"
        subtitle="What the bot is considering this cycle"
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
          <CardContent className="text-sm font-data">{ranked.length || staticSymbols.length}</CardContent>
        </Card>
      </div>

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
