"use client";

import { useEffect, useState } from "react";
import { BrainCircuit } from "lucide-react";
import { getDecisionFrameworks, type DecisionFramework } from "@/lib/api";

type State =
  | { status: "loading" }
  | { status: "empty" }
  | { status: "ready"; frameworks: DecisionFramework[] }
  | { status: "error" };

function ConfidenceBadge({ badge, revision }: { badge: DecisionFramework["badge"]; revision: number }) {
  const chips: React.ReactNode[] = [];

  if (badge === "high") {
    chips.push(
      <span
        key="confidence"
        className="inline-flex items-center gap-1 rounded-full bg-green-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-green-700 dark:text-green-400"
      >
        HIGH CONFIDENCE ✓
      </span>,
    );
  } else if (badge === "low") {
    chips.push(
      <span
        key="confidence"
        className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-400"
      >
        LOW CONFIDENCE ⚠
      </span>,
    );
  } else {
    chips.push(
      <span
        key="confidence"
        className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
      >
        NEUTRAL
      </span>,
    );
  }

  if (revision > 0) {
    chips.push(
      <span
        key="revision"
        className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
        data-testid="validated-pill"
      >
        validated {revision}×
      </span>,
    );
  }

  return <div className="flex flex-wrap gap-1">{chips}</div>;
}

function FrameworkRow({ fw }: { fw: DecisionFramework }) {
  return (
    <div
      className="rounded-lg border border-border/60 bg-card/50 px-3 py-2.5 space-y-1.5"
      data-testid="framework-row"
    >
      {fw.trigger && (
        <p className="text-[11px] leading-snug">
          <span className="font-medium text-muted-foreground uppercase tracking-wide text-[9px]">when </span>
          <span className="text-foreground/90">{fw.trigger}</span>
        </p>
      )}
      {fw.action && (
        <p className="text-[11px] leading-snug">
          <span className="font-medium text-muted-foreground uppercase tracking-wide text-[9px]">then </span>
          <span className="text-foreground/90">{fw.action}</span>
        </p>
      )}
      {fw.value && (
        <p className="text-[11px] leading-snug">
          <span className="font-medium text-muted-foreground uppercase tracking-wide text-[9px]">value </span>
          <span className="text-foreground/80 italic">{fw.value}</span>
        </p>
      )}
      <ConfidenceBadge badge={fw.badge} revision={fw.revision} />
    </div>
  );
}

export function DecisionFrameworksCard({ username }: { username: string }) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    getDecisionFrameworks(username, 10)
      .then((data) => {
        if (cancelled) return;
        if (!data.frameworks || data.frameworks.length === 0) {
          setState({ status: "empty" });
        } else {
          setState({ status: "ready", frameworks: data.frameworks });
        }
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });

    return () => {
      cancelled = true;
    };
  }, [username]);

  // Don't render anything if loading failed or no data yet
  if (state.status === "loading" || state.status === "empty" || state.status === "error") {
    return null;
  }

  return (
    <section
      className="rounded-xl border border-border/60 bg-card/80 p-4 shadow-sm"
      aria-label="Decision Frameworks"
    >
      <div className="mb-3 space-y-1">
        <div className="flex items-center gap-2">
          <BrainCircuit className="h-4 w-4 text-chart-1" />
          <h2 className="text-sm font-semibold">Decision Frameworks</h2>
        </div>
        <p className="text-xs text-muted-foreground">How this engineer makes calls</p>
      </div>

      <div className="space-y-2">
        {state.frameworks.map((fw, i) => (
          <FrameworkRow key={fw.framework_id ?? i} fw={fw} />
        ))}
      </div>
    </section>
  );
}
