import { useEffect, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { PageHeader } from "@/components/PageHeader";
import { LiveBanner } from "@/components/LiveBanner";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useConfig, usePatchSettings } from "@/hooks/useApi";
import { toast } from "sonner";
import { AlertTriangle, RotateCcw, Save } from "lucide-react";
import type { AppConfig } from "@/lib/types";

const RISK_BOUNDS = {
  max_risk_per_trade_pct: { min: 0.005, max: 0.05, step: 0.001, label: "Max risk / trade (fraction)" },
  max_open_risk_pct: { min: 0.02, max: 0.15, step: 0.01, label: "Max open risk (fraction)" },
  daily_loss_limit_pct: { min: 0.01, max: 0.1, step: 0.01, label: "Daily loss halt (fraction)" },
  max_drawdown_pct: { min: 0.05, max: 0.25, step: 0.01, label: "Max drawdown (fraction)" },
  max_concurrent_positions: { min: 1, max: 5, step: 1, label: "Max positions" },
};

export default function Settings() {
  const { data: cfg } = useConfig();
  const patch = usePatchSettings();
  const [draft, setDraft] = useState<AppConfig | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(cfg);

  useEffect(() => { if (cfg) setDraft(structuredClone(cfg)); }, [cfg]);

  if (!draft) {
    return (
      <div>
        <PageHeader title="Settings" />
        <p className="text-sm text-muted-foreground">Loading config…</p>
      </div>
    );
  }

  const save = async (changes: Partial<AppConfig>) => {
    try {
      const r = await patch.mutateAsync(changes);
      toast.success(r.message || "Settings saved", {
        description: r.requires_restart ? "Restart bot for changes to take effect." : undefined,
      });
    } catch (e: any) {
      toast.error(`Save failed: ${e.message}`);
    }
  };

  const symbolsText = draft.symbols.join(", ");

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="Edit bot configuration. Changes are proposed via PATCH; some require a restart."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!dirty}
              onClick={() => cfg && setDraft(structuredClone(cfg))}
              className="gap-2"
            >
              <RotateCcw className="h-4 w-4" /> Reset
            </Button>
            <Button
              size="sm"
              disabled={!dirty || patch.isPending}
              onClick={() => save(draft)}
              className="gap-2"
            >
              <Save className="h-4 w-4" /> {patch.isPending ? "Saving…" : "Save all"}
            </Button>
          </div>
        }
      />
      <LiveBanner />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* Trading mode */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-display">Trading mode</CardTitle>
            <CardDescription>Asset class & broker mode</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label className="text-xs mb-2 block">Asset class</Label>
              <RadioGroup
                value={draft.asset_class}
                onValueChange={(v) => setDraft({ ...draft, asset_class: v as any })}
                className="flex gap-4"
              >
                <label className="flex items-center gap-2 text-sm">
                  <RadioGroupItem value="crypto" /> Crypto
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <RadioGroupItem value="equities" /> Equities
                </label>
              </RadioGroup>
              {cfg && cfg.asset_class !== draft.asset_class && (
                <p className="mt-2 text-xs text-accent-orange">Requires bot restart.</p>
              )}
            </div>
            <Alert>
              <AlertDescription className="text-xs">
                Paper trading:{" "}
                <span className="font-data font-semibold">
                  {draft.paper_trading ? "ON (paper)" : "OFF (LIVE)"}
                </span>{" "}
                — read-only. Switch on backend to change.
              </AlertDescription>
            </Alert>
          </CardContent>
        </Card>

        {/* Symbols & universe */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-display">Symbols & universe</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label className="text-xs">Static symbols (comma-separated)</Label>
              <Input
                value={symbolsText}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    symbols: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                  })
                }
                className="font-data"
              />
            </div>
            <div className="flex items-center justify-between">
              <Label className="text-sm">Screener enabled</Label>
              <Switch
                checked={draft.screener.enabled}
                onCheckedChange={(v) =>
                  setDraft({ ...draft, screener: { ...draft.screener, enabled: v } })
                }
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <NumField label="Top N" value={draft.screener.top_n} onChange={(v) => setDraft({ ...draft, screener: { ...draft.screener, top_n: v } })} />
              <NumField label="Refresh (s)" value={draft.screener.refresh_seconds} onChange={(v) => setDraft({ ...draft, screener: { ...draft.screener, refresh_seconds: v } })} />
              <NumField label="Min ATR %" step={0.1} value={draft.screener.min_atr_pct} onChange={(v) => setDraft({ ...draft, screener: { ...draft.screener, min_atr_pct: v } })} />
              <NumField label="Min $ volume" value={draft.screener.min_dollar_volume} onChange={(v) => setDraft({ ...draft, screener: { ...draft.screener, min_dollar_volume: v } })} />
            </div>
            {draft.asset_class === "equities" && (
              <div>
                <Label className="text-xs">Movers source</Label>
                <Select
                  value={draft.screener.movers_source}
                  onValueChange={(v) =>
                    setDraft({ ...draft, screener: { ...draft.screener, movers_source: v as any } })
                  }
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="actives">actives</SelectItem>
                    <SelectItem value="gainers">gainers</SelectItem>
                    <SelectItem value="losers">losers</SelectItem>
                    <SelectItem value="both">both</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Strategy */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-display">Strategy</CardTitle>
            <CardDescription>Changes apply on next bot restart.</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3">
            <NumField label="RSI oversold" value={draft.strategy.rsi_oversold} onChange={(v) => setDraft({ ...draft, strategy: { ...draft.strategy, rsi_oversold: v } })} />
            <NumField label="RSI overbought" value={draft.strategy.rsi_overbought} onChange={(v) => setDraft({ ...draft, strategy: { ...draft.strategy, rsi_overbought: v } })} />
            <NumField label="Stop loss %" step={0.1} value={draft.strategy.stop_loss_pct} onChange={(v) => setDraft({ ...draft, strategy: { ...draft.strategy, stop_loss_pct: v } })} />
            <NumField label="Take profit %" step={0.1} value={draft.strategy.take_profit_pct} onChange={(v) => setDraft({ ...draft, strategy: { ...draft.strategy, take_profit_pct: v } })} />
            <NumField label="Max hold (min)" value={draft.strategy.max_hold_minutes} onChange={(v) => setDraft({ ...draft, strategy: { ...draft.strategy, max_hold_minutes: v } })} />
            <div className="col-span-2 flex items-center justify-between pt-2">
              <Label className="text-sm">Require 15m uptrend</Label>
              <Switch
                checked={draft.strategy.require_15m_uptrend}
                onCheckedChange={(v) => setDraft({ ...draft, strategy: { ...draft.strategy, require_15m_uptrend: v } })}
              />
            </div>
            <div className="col-span-2 flex items-center justify-between">
              <Label className="text-sm">Require volume spike</Label>
              <Switch
                checked={draft.strategy.require_volume_spike}
                onCheckedChange={(v) => setDraft({ ...draft, strategy: { ...draft.strategy, require_volume_spike: v } })}
              />
            </div>
          </CardContent>
        </Card>

        {/* Risk */}
        <Card className="border-destructive/30">
          <CardHeader>
            <CardTitle className="text-sm font-display flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-destructive" /> Risk limits
            </CardTitle>
            <CardDescription>Hard bounds enforced — changes require confirmation.</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3">
            {Object.entries(RISK_BOUNDS).map(([key, b]) => (
              <NumField
                key={key}
                label={b.label}
                value={(draft.risk as any)[key]}
                step={"step" in b ? b.step : 0.1}
                onChange={(v) =>
                  setDraft({
                    ...draft,
                    risk: { ...draft.risk, [key]: Math.max(b.min, Math.min(b.max, v)) },
                  })
                }
              />
            ))}
            <NumField
              label="Trading capital ($ virtual)"
              value={draft.risk.trading_capital ?? 0}
              step={500}
              onChange={(v) =>
                setDraft({ ...draft, risk: { ...draft.risk, trading_capital: Math.max(0, v) } })
              }
            />
            <NumField
              label="Max notional / trade (fraction, 0.2 = 20%)"
              value={draft.risk.max_notional_pct ?? 0.2}
              step={0.05}
              onChange={(v) =>
                setDraft({
                  ...draft,
                  risk: { ...draft.risk, max_notional_pct: Math.max(0.05, Math.min(0.5, v)) },
                })
              }
            />
            <div className="col-span-2 pt-2">
              <ConfirmDialog
                trigger={
                  <Button size="sm" variant="destructive" className="w-full" disabled={!dirty}>
                    Save risk changes
                  </Button>
                }
                title="Confirm risk limit changes?"
                description="These limits constrain real losses. Make sure new values are intentional."
                destructive
                requireTyping="CONFIRM"
                confirmText="Apply risk changes"
                onConfirm={() => save({ risk: draft.risk })}
              />
            </div>
          </CardContent>
        </Card>

        {/* Runtime */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-display">Runtime</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-3">
            <NumField
              label="Scan interval (s) 30–300"
              value={draft.runtime.scan_interval_seconds}
              onChange={(v) =>
                setDraft({
                  ...draft,
                  runtime: { ...draft.runtime, scan_interval_seconds: Math.max(30, Math.min(300, v)) },
                })
              }
            />
            <div>
              <Label className="text-xs">Log level</Label>
              <Select
                value={draft.runtime.log_level}
                onValueChange={(v) =>
                  setDraft({ ...draft, runtime: { ...draft.runtime, log_level: v as any } })
                }
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["DEBUG", "INFO", "WARNING", "ERROR"].map((l) => (
                    <SelectItem key={l} value={l}>{l}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function NumField({
  label,
  value,
  onChange,
  step = 1,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <Input
        type="number"
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="font-data"
      />
    </div>
  );
}
