import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  Account,
  ActivityEvent,
  AppConfig,
  BotActionResult,
  Health,
  LogsResponse,
  SettingsPatchResult,
  Stats,
  Status,
  Watchlist,
} from "@/lib/types";

const KEYS = {
  health: ["health"] as const,
  status: ["status"] as const,
  account: ["account"] as const,
  config: ["config"] as const,
  stats: ["stats"] as const,
  watchlist: ["watchlist"] as const,
  events: (params: Record<string, string | number | undefined>) =>
    ["events", params] as const,
  logs: (tail: number) => ["logs", tail] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: KEYS.health,
    queryFn: () => api.get<Health>("/api/health"),
    refetchInterval: 10_000,
  });
}

export function useStatus() {
  return useQuery({
    queryKey: KEYS.status,
    queryFn: () => api.get<Status>("/api/status"),
    refetchInterval: 5_000,
  });
}

export function useAccount() {
  return useQuery({
    queryKey: KEYS.account,
    queryFn: () => api.get<Account>("/api/account"),
    refetchInterval: 5_000,
  });
}

export function useConfig() {
  return useQuery({
    queryKey: KEYS.config,
    queryFn: () => api.get<AppConfig>("/api/config"),
    refetchInterval: 30_000,
  });
}

export function useStats() {
  return useQuery({
    queryKey: KEYS.stats,
    queryFn: () => api.get<Stats>("/api/stats"),
    refetchInterval: 10_000,
  });
}

export function useWatchlist() {
  return useQuery({
    queryKey: KEYS.watchlist,
    queryFn: () => api.get<Watchlist>("/api/watchlist"),
    refetchInterval: 15_000,
  });
}

export function useEvents(params: {
  limit?: number;
  kind?: string;
  symbol?: string;
} = {}) {
  const search = new URLSearchParams();
  if (params.limit) search.set("limit", String(params.limit));
  if (params.kind) search.set("kind", params.kind);
  if (params.symbol) search.set("symbol", params.symbol);
  const qs = search.toString();
  return useQuery({
    queryKey: KEYS.events(params as any),
    queryFn: () =>
      api.get<ActivityEvent[]>(`/api/events${qs ? `?${qs}` : ""}`),
    refetchInterval: 7_000,
  });
}

export function useLogs(tail = 50, enabled = true) {
  return useQuery({
    queryKey: KEYS.logs(tail),
    queryFn: () => api.get<LogsResponse>(`/api/logs?tail=${tail}`),
    refetchInterval: enabled ? 3_000 : false,
    enabled,
  });
}

export function useBotAction(action: "start" | "stop" | "restart" | "health-check" | "once") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<BotActionResult>(`/api/bot/${action}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.status });
      qc.invalidateQueries({ queryKey: KEYS.health });
      qc.invalidateQueries({ queryKey: KEYS.account });
    },
  });
}

export function usePatchSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<AppConfig>) =>
      api.patch<SettingsPatchResult>("/api/settings", patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.config }),
  });
}
