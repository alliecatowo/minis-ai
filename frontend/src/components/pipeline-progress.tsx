"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { Check, Loader2, Circle } from "lucide-react";

const PIPELINE_STEPS = [
  {
    key: "fetch",
    label: "Fetching evidence",
    detail: "Collecting commits, PRs, reviews, and profile context.",
  },
  {
    key: "explore",
    label: "Exploring judgment",
    detail: "Extracting values, heuristics, and recurring review behavior.",
  },
  {
    key: "synthesize",
    label: "Synthesizing review model",
    detail: "Turning extracted evidence into a usable mini.",
  },
  {
    key: "save",
    label: "Saving result",
    detail: "Persisting the profile, prompts, and structured frameworks.",
  },
];

type StepStatus = "pending" | "active" | "complete";

function normalizeStep(step: string): string {
  const key = step.toLowerCase().trim();

  if (["fetch", "fetching"].includes(key)) return "fetch";
  if (["format", "extract", "explore", "exploring"].includes(key)) return "explore";
  if (["synthesize", "synthesizing"].includes(key)) return "synthesize";
  if (["save", "saving", "done", "complete", "completed"].includes(key)) return "save";

  return key;
}

function getStepStatuses(currentStep: string, progress: number): StepStatus[] {
  if (progress >= 100) {
    return PIPELINE_STEPS.map(() => "complete");
  }

  const currentIndex = PIPELINE_STEPS.findIndex((s) => s.key === normalizeStep(currentStep));
  return PIPELINE_STEPS.map((_, i) => {
    if (currentIndex === -1) return i === 0 ? "active" : "pending";
    if (i < currentIndex) return "complete";
    if (i === currentIndex) return "active";
    return "pending";
  });
}

function useElapsedTime() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return mins > 0
    ? `${mins}m ${secs.toString().padStart(2, "0")}s`
    : `${secs}s`;
}

export function PipelineProgress({
  currentStep,
  message,
  progress,
}: {
  currentStep: string;
  message: string;
  progress: number;
}) {
  const statuses = getStepStatuses(currentStep, progress);
  const elapsed = useElapsedTime();
  const safeProgress = Math.min(Math.max(progress, 0), 100);

  return (
    <div className="w-full max-w-md space-y-6">
      {/* Progress bar */}
      <div className="space-y-2">
        <div className="h-1 w-full overflow-hidden rounded-full bg-secondary">
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{ width: `${safeProgress}%` }}
          />
        </div>
        <div className="flex items-center justify-between">
          <p className="font-mono text-xs text-muted-foreground">
            {message || "Starting..."}
          </p>
          <p className="font-mono text-xs text-muted-foreground/60">
            {elapsed}
          </p>
        </div>
        <p className="text-xs text-muted-foreground/70">
          You can leave this page open while the model builds. It will redirect
          to the mini when the result is ready.
        </p>
      </div>

      {/* Steps */}
      <div className="space-y-3">
        {PIPELINE_STEPS.map((step, i) => {
          const status = statuses[i];
          return (
            <div
              key={step.key}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 transition-all",
                status === "active" && "bg-secondary",
                status === "complete" && "opacity-70"
              )}
            >
              <div className="flex h-5 w-5 shrink-0 items-center justify-center">
                {status === "complete" ? (
                  <Check className="h-4 w-4 text-emerald-400" />
                ) : status === "active" ? (
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                ) : (
                  <Circle className="h-3 w-3 text-muted-foreground/50" />
                )}
              </div>
              <span
                className={cn(
                  "text-sm",
                  status === "active" && "font-medium text-foreground",
                  status === "pending" && "text-muted-foreground/50",
                  status === "complete" && "text-muted-foreground"
                )}
              >
                {step.label}
              </span>
              {status === "active" && (
                <span className="hidden flex-1 text-right text-xs text-muted-foreground sm:block">
                  {step.detail}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
