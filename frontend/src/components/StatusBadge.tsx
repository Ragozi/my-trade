import { cn } from "@/lib/utils";
import type { BotStatus } from "@/lib/types";

const STYLES: Record<BotStatus, string> = {
  RUNNING: "bg-accent/15 text-accent border-accent/30",
  STOPPED: "bg-muted text-muted-foreground border-border",
  HALTED: "bg-accent-orange/15 text-accent-orange border-accent-orange/30",
  ERROR: "bg-destructive/15 text-destructive border-destructive/40",
};

export function StatusBadge({ status, className }: { status: BotStatus; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-semibold font-data tracking-wider uppercase",
        STYLES[status],
        className,
      )}
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full",
          status === "RUNNING" && "bg-accent animate-pulse-dot",
          status === "HALTED" && "bg-accent-orange",
          status === "ERROR" && "bg-destructive",
          status === "STOPPED" && "bg-muted-foreground",
        )}
      />
      {status}
    </span>
  );
}

export function ModeBadge({ paper }: { paper: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-bold font-data tracking-widest uppercase",
        paper
          ? "bg-primary/10 text-primary border-primary/30"
          : "bg-destructive/15 text-destructive border-destructive/40",
      )}
    >
      {paper ? "PAPER" : "LIVE"}
    </span>
  );
}
