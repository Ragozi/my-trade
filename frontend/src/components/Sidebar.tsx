import { NavLink } from "react-router-dom";
import {
  Activity,
  BarChart3,
  Briefcase,
  BookOpen,
  ListTree,
  Radar,
  ShieldAlert,
  Settings as SettingsIcon,
  Power,
} from "lucide-react";
import { useHealth, useStatus } from "@/hooks/useApi";
import { ModeBadge, StatusBadge } from "@/components/StatusBadge";
import type { BotStatus } from "@/lib/types";

const navigation = [
  { name: "Dashboard", href: "/", icon: BarChart3 },
  { name: "Positions", href: "/positions", icon: Briefcase },
  { name: "Activity", href: "/activity", icon: ListTree },
  { name: "Watchlist", href: "/watchlist", icon: Radar },
  { name: "Knowledge", href: "/knowledge", icon: BookOpen },
  { name: "Bot Control", href: "/control", icon: Power },
  { name: "Risk & Halts", href: "/risk", icon: ShieldAlert },
  { name: "Settings", href: "/settings", icon: SettingsIcon },
];

function deriveStatus(
  status: ReturnType<typeof useStatus>["data"],
  health: ReturnType<typeof useHealth>["data"],
): BotStatus {
  if (!status && !health) return "STOPPED";
  if (status?.halted) return "HALTED";
  if (status?.bot?.running || health?.bot_running) return "RUNNING";
  return "STOPPED";
}

export function Sidebar() {
  const { data: status, isError: statusErr } = useStatus();
  const { data: health, isError: healthErr } = useHealth();
  const offline = statusErr && healthErr;
  const botStatus: BotStatus = offline ? "ERROR" : deriveStatus(status, health);
  const paper = health?.paper_trading ?? true;
  const assetClass = health?.asset_class ?? status?.session?.asset_class ?? "—";

  return (
    <div className="fixed left-0 top-0 h-screen w-64 bg-card/80 backdrop-blur-xl border-r border-border flex flex-col z-50">
      <div className="p-6 border-b border-border">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center border border-primary/20">
            <Activity className="h-4 w-4 text-primary" />
          </div>
          <div>
            <h1 className="text-base font-semibold font-display tracking-tight text-foreground">
              MY-TRADE
            </h1>
            <p className="text-[10px] text-muted-foreground font-medium tracking-wider uppercase">
              Operator Console
            </p>
          </div>
        </div>
      </div>

      <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
        {navigation.map((item) => (
          <NavLink
            key={item.name}
            to={item.href}
            end={item.href === "/"}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              }`
            }
          >
            <item.icon className="h-4 w-4" />
            {item.name}
          </NavLink>
        ))}
      </nav>

      <div className="p-4 mx-3 mb-3 rounded-lg bg-secondary/50 border border-border space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Bot</span>
          <StatusBadge status={botStatus} />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Mode</span>
          <ModeBadge paper={paper} />
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Asset</span>
          <span className="font-data text-foreground uppercase">{assetClass}</span>
        </div>
      </div>
    </div>
  );
}
