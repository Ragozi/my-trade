import { Link } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/PageHeader";
import { LiveBanner } from "@/components/LiveBanner";
import { useAccount } from "@/hooks/useApi";
import { fmtNum, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Briefcase } from "lucide-react";

export default function Positions() {
  const { data: account, isLoading, error } = useAccount();
  const positions = account?.positions ?? [];

  return (
    <div>
      <PageHeader title="Positions" subtitle="Open positions reported by the broker" />
      <LiveBanner />

      {error && (
        <div className="mb-4 text-sm text-destructive">Failed to load: {(error as Error).message}</div>
      )}

      <Card>
        <CardContent className="p-0">
          {positions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-muted-foreground gap-2">
              <Briefcase className="h-8 w-8 opacity-50" />
              <div className="text-sm">{isLoading ? "Loading..." : "Flat — no open positions"}</div>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Avg entry</TableHead>
                  <TableHead className="text-right">Market value</TableHead>
                  <TableHead className="text-right">Unrealized P&L</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {positions.map((p) => (
                  <TableRow key={p.symbol}>
                    <TableCell className="font-data font-semibold">
                      <Link
                        to={`/activity?symbol=${encodeURIComponent(p.symbol)}`}
                        className="text-primary hover:underline"
                      >
                        {p.symbol}
                      </Link>
                    </TableCell>
                    <TableCell className="text-right font-data">{fmtNum(p.qty, 4)}</TableCell>
                    <TableCell className="text-right font-data">{fmtUsd(p.avg_entry_price)}</TableCell>
                    <TableCell className="text-right font-data">{fmtUsd(p.market_value)}</TableCell>
                    <TableCell
                      className={cn(
                        "text-right font-data font-semibold",
                        p.unrealized_pl >= 0 ? "text-accent" : "text-destructive",
                      )}
                    >
                      {fmtUsd(p.unrealized_pl)}
                    </TableCell>
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
