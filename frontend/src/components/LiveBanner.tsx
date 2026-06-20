import { AlertTriangle } from "lucide-react";
import { useHealth } from "@/hooks/useApi";

export function LiveBanner() {
  const { data: health } = useHealth();
  if (!health || health.paper_trading) return null;
  return (
    <div className="mb-4 flex items-center gap-3 px-4 py-2.5 rounded-lg border border-destructive/40 bg-destructive/10 text-destructive">
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <div className="text-sm font-medium">
        LIVE TRADING — real money orders are being placed. Double-check risk limits before
        starting the bot.
      </div>
    </div>
  );
}
