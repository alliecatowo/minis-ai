"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Gauge, LoaderCircle, Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  AgreementSummaryUnavailableError,
  getAgreementSummary,
  type AgreementMetricSummary,
  type AgreementSummary,
} from "@/lib/api";

type AgreementState =
  | { status: "loading" }
  | { status: "ready"; data: AgreementSummary }
  | { status: "unavailable"; message: string }
  | { status: "error"; message: string };

const SCORECARD_METRICS = [
  { key: "approval_accuracy", label: "Approval Accuracy" },
  { key: "blocker_precision", label: "Blocker Precision" },
  { key: "comment_f1", label: "Comment F1" },
] as const;

function formatPercent(value: number | null): string {
  if (value === null) return "—";
  return `${Math.round(value * 100)}%`;
}

function formatCycleLabel(count: number): string {
  return `${count} reviewed PR${count === 1 ? "" : "s"}`;
}

function TrendChip({ metric }: { metric: AgreementMetricSummary }) {
  if (metric.trend === null || Math.abs(metric.trend) < 0.001) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
        <Minus className="h-3 w-3" />
        Flat
      </span>
    );
  }

  const positive = metric.trend > 0;
  const Icon = positive ? TrendingUp : TrendingDown;

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ${
        positive
          ? "bg-emerald-500/10 text-emerald-700"
          : "bg-amber-500/10 text-amber-700"
      }`}
    >
      <Icon className="h-3 w-3" />
      {positive ? "+" : ""}
      {Math.round(metric.trend * 100)} pts
    </span>
  );
}

export function AgreementScorecardCard({ username }: { username: string }) {
  const [state, setState] = useState<AgreementState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    getAgreementSummary(username)
      .then((data) => {
        if (!cancelled) {
          setState({ status: "ready", data });
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;

        if (error instanceof AgreementSummaryUnavailableError) {
          setState({ status: "unavailable", message: error.message });
          return;
        }

        setState({
          status: "error",
          message: error instanceof Error ? error.message : "Failed to load agreement summary.",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [username]);

  return (
    <section className="rounded-xl border border-border/60 bg-card/80 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Gauge className="h-4 w-4 text-chart-1" />
            <h2 className="text-sm font-semibold">Agreement Scorecard</h2>
          </div>
          <p className="text-xs text-muted-foreground">
            Owner-only snapshot of how often predicted review behavior matched the human outcome.
          </p>
        </div>
        <Badge variant="secondary" className="shrink-0 text-[10px] uppercase tracking-wide">
          Owner only
        </Badge>
      </div>

      {state.status === "loading" && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-dashed border-border/70 px-3 py-3 text-xs text-muted-foreground">
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
          Loading agreement summary...
        </div>
      )}

      {state.status === "unavailable" && (
        <div className="mt-4 rounded-lg border border-dashed border-border/70 bg-secondary/20 p-3">
          <p className="text-xs font-medium text-foreground">Agreement backend dependency not merged</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {state.message} The card will populate once the backend summary route is available.
          </p>
        </div>
      )}

      {state.status === "error" && (
        <div className="mt-4 rounded-lg border border-destructive/20 bg-destructive/5 p-3">
          <div className="flex items-center gap-2 text-xs font-medium text-destructive">
            <AlertCircle className="h-3.5 w-3.5" />
            Could not load the agreement summary
          </div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{state.message}</p>
        </div>
      )}

      {state.status === "ready" && state.data.cycle_count === 0 && (
        <div className="mt-4 rounded-lg border border-dashed border-border/70 bg-secondary/20 p-3">
          <p className="text-xs font-medium text-foreground">No scored reviews yet</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            This card populates after the first review cycle has both a prediction and a human outcome.
          </p>
        </div>
      )}

      {state.status === "ready" && state.data.cycle_count > 0 && (
        <div className="mt-4 space-y-3">
          <div className="flex items-center justify-between rounded-lg bg-secondary/30 px-3 py-2">
            <span className="text-xs text-muted-foreground">Coverage</span>
            <span className="text-xs font-medium">{formatCycleLabel(state.data.cycle_count)}</span>
          </div>

          <div className="space-y-2">
            {SCORECARD_METRICS.map(({ key, label }) => {
              const metric = state.data.metrics[key];

              return (
                <div
                  key={key}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border/60 px-3 py-2"
                >
                  <div className="min-w-0">
                    <p className="text-xs font-medium">{label}</p>
                    <p className="text-[11px] text-muted-foreground">
                      {formatPercent(metric.value)}
                    </p>
                  </div>
                  <TrendChip metric={metric} />
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
