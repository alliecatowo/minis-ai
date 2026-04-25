"use client";

import { type FormEvent, useState } from "react";
import { CheckCircle2, ChevronDown, Loader2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  reviewArtifact,
  saveReviewCyclePrediction,
  saveReviewCycleOutcome,
  type ArtifactReviewResponse,
  type ArtifactReviewOutcomeValue,
  type ArtifactOutcomeCapture,
  type ArtifactReviewType,
  type ReviewPredictionSignal,
} from "@/lib/api";

const ARTIFACT_OPTIONS: Array<{ value: ArtifactReviewType; label: string }> = [
  { value: "design_doc", label: "Design doc" },
  { value: "issue_plan", label: "Issue plan" },
];

type PrivateAssessmentListKey = Exclude<
  keyof ArtifactReviewResponse["private_assessment"],
  "confidence"
>;

const SIGNAL_SECTIONS: Array<{
  key: PrivateAssessmentListKey;
  label: string;
  empty: string;
}> = [
  {
    key: "blocking_issues",
    label: "Blocking issues",
    empty: "No blocking issues surfaced.",
  },
  {
    key: "non_blocking_issues",
    label: "Non-blocking issues",
    empty: "No non-blocking issues surfaced.",
  },
  {
    key: "open_questions",
    label: "Open questions",
    empty: "No open questions surfaced.",
  },
  {
    key: "positive_signals",
    label: "Positive signals",
    empty: "No positive signals surfaced.",
  },
];

const OUTCOME_OPTIONS: Array<{ value: ArtifactReviewOutcomeValue; label: string; className: string }> = [
  { value: "accepted", label: "Accepted", className: "border-emerald-500/50 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20" },
  { value: "revised", label: "Revised", className: "border-sky-500/50 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20" },
  { value: "deferred", label: "Deferred", className: "border-amber-500/50 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20" },
  { value: "rejected", label: "Rejected", className: "border-red-500/50 bg-red-500/10 text-red-300 hover:bg-red-500/20" },
];

const ARTIFACT_DISPOSITION_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "shipped_as_proposed", label: "Shipped as proposed" },
  { value: "shipped_with_modifications", label: "Shipped with modifications" },
  { value: "abandoned", label: "Abandoned" },
  { value: "superseded", label: "Superseded" },
];

function formatLabel(value: string) {
  return value.replaceAll("_", " ");
}

function approvalTone(
  approvalState: ArtifactReviewResponse["expressed_feedback"]["approval_state"],
) {
  switch (approvalState) {
    case "approve":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
    case "request_changes":
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
    case "comment":
      return "border-sky-500/30 bg-sky-500/10 text-sky-200";
    default:
      return "border-border/60 bg-secondary/50 text-muted-foreground";
  }
}

function OutcomeButton({
  value,
  selected,
  onClick,
}: {
  value: ArtifactReviewOutcomeValue;
  selected: boolean;
  onClick: () => void;
}) {
  const opt = OUTCOME_OPTIONS.find((o) => o.value === value)!;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded border px-2 py-0.5 text-[11px] font-medium transition-colors",
        selected ? opt.className : "border-border/60 bg-transparent text-muted-foreground hover:border-border",
      )}
    >
      {opt.label}
    </button>
  );
}

function SignalWithOutcome({
  signal,
  outcome,
  onOutcomeChange,
  showOutcome,
}: {
  signal: ReviewPredictionSignal;
  outcome: ArtifactReviewOutcomeValue | null;
  onOutcomeChange: (value: ArtifactReviewOutcomeValue | null) => void;
  showOutcome: boolean;
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-background/60 p-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-foreground">{signal.summary}</p>
        <Badge variant="outline" className="shrink-0 text-[10px] uppercase">
          {Math.round(signal.confidence * 100)}%
        </Badge>
      </div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{signal.rationale}</p>
      {showOutcome && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {OUTCOME_OPTIONS.map((opt) => (
            <OutcomeButton
              key={opt.value}
              value={opt.value}
              selected={outcome === opt.value}
              onClick={() => onOutcomeChange(outcome === opt.value ? null : opt.value)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SignalList({
  signals,
  empty,
  outcomeMap,
  onOutcomeChange,
  showOutcome,
}: {
  signals: ReviewPredictionSignal[];
  empty: string;
  outcomeMap: Record<string, ArtifactReviewOutcomeValue | null>;
  onOutcomeChange: (key: string, value: ArtifactReviewOutcomeValue | null) => void;
  showOutcome: boolean;
}) {
  if (signals.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }

  return (
    <div className="space-y-3">
      {signals.map((signal) => (
        <SignalWithOutcome
          key={signal.key}
          signal={signal}
          outcome={outcomeMap[signal.key] ?? null}
          onOutcomeChange={(v) => onOutcomeChange(signal.key, v)}
          showOutcome={showOutcome}
        />
      ))}
    </div>
  );
}

export function DraftReviewPanel({
  miniId,
  miniUsername,
  isOwner = false,
}: {
  miniId: string;
  miniUsername: string;
  isOwner?: boolean;
}) {
  const [artifactType, setArtifactType] = useState<ArtifactReviewType>("design_doc");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [result, setResult] = useState<ArtifactReviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Outcome capture state
  const [externalId, setExternalId] = useState<string | null>(null);
  const [outcomeMap, setOutcomeMap] = useState<Record<string, ArtifactReviewOutcomeValue | null>>({});
  const [artifactDisposition, setArtifactDisposition] = useState<string>("");
  const [reviewerSummary, setReviewerSummary] = useState("");
  const [savingOutcome, setSavingOutcome] = useState(false);
  const [outcomeSaved, setOutcomeSaved] = useState(false);
  const [outcomeError, setOutcomeError] = useState<string | null>(null);

  const formInvalid = title.trim().length === 0 || body.trim().length === 0 || submitting;
  const unavailableReason =
    result && result.prediction_available !== true
      ? (result.unavailable_reason ?? "review prediction is gated")
      : result && result.mode !== "llm"
        ? `unsupported review prediction mode: ${result.mode}`
        : result?.unavailable_reason
          ? "available prediction included unavailable_reason"
          : null;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setResult(null);
    setOutcomeMap({});
    setArtifactDisposition("");
    setReviewerSummary("");
    setOutcomeSaved(false);
    setOutcomeError(null);

    try {
      const nextResult = await reviewArtifact(miniId, {
        artifact_type: artifactType,
        title: title.trim(),
        artifact_summary: body.trim(),
      });
      setResult(nextResult);

      // Generate a stable external_id from title + timestamp
      const id = `artifact-review:${Date.now()}:${title.trim().slice(0, 40).replace(/\s+/g, "-").toLowerCase()}`;
      setExternalId(id);

      // Persist the prediction so outcomes can be linked later (best-effort)
      if (isOwner) {
        saveReviewCyclePrediction(miniId, {
          external_id: id,
          source_type: "artifact_review",
          predicted_state: {
            private_assessment: nextResult.private_assessment,
            expressed_feedback: nextResult.expressed_feedback,
            delivery_policy: nextResult.delivery_policy,
          },
        }).catch((e: unknown) => console.warn("[outcome] saveReviewCyclePrediction failed:", e));
      }
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to review artifact");
    } finally {
      setSubmitting(false);
    }
  }

  function handleOutcomeChange(key: string, value: ArtifactReviewOutcomeValue | null) {
    setOutcomeMap((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSaveOutcome() {
    if (!result || !externalId) return;
    setSavingOutcome(true);
    setOutcomeError(null);

    // Collect all signals that have an outcome set
    const suggestionOutcomes = Object.entries(outcomeMap)
      .filter(([, v]) => v !== null)
      .map(([key, outcome]) => ({ suggestion_key: key, outcome: outcome! }));

    const outcomeCapture: ArtifactOutcomeCapture = {
      suggestion_outcomes: suggestionOutcomes,
      ...(artifactDisposition && { final_disposition: artifactDisposition }),
      ...(reviewerSummary.trim() && { reviewer_summary: reviewerSummary.trim() }),
    };

    try {
      await saveReviewCycleOutcome(miniId, {
        external_id: externalId,
        source_type: "artifact_review",
        human_review_outcome: {
          private_assessment: {
            blocking_issues: [],
            non_blocking_issues: [],
            open_questions: [],
            positive_signals: [],
            confidence: result.private_assessment.confidence,
          },
          expressed_feedback: {
            summary: reviewerSummary.trim() || result.expressed_feedback.summary,
            comments: [],
            approval_state: result.expressed_feedback.approval_state,
          },
          outcome_capture: outcomeCapture,
        },
      });
      setOutcomeSaved(true);
    } catch (e: unknown) {
      setOutcomeError(e instanceof Error ? e.message : "Failed to save outcome");
    } finally {
      setSavingOutcome(false);
    }
  }

  const allSignals = result
    ? ([
        ...result.private_assessment.blocking_issues,
        ...result.private_assessment.non_blocking_issues,
        ...result.private_assessment.open_questions,
        ...result.private_assessment.positive_signals,
      ] as ReviewPredictionSignal[])
    : [];

  const capturedCount = allSignals.filter((s) => outcomeMap[s.key] !== null && outcomeMap[s.key] !== undefined).length;

  return (
    <Card className="mt-6 gap-4 border-border/60 bg-card/95 shadow-none">
      <CardHeader className="gap-1">
        <CardTitle className="text-base">Review a draft</CardTitle>
        <CardDescription className="leading-5">
          Paste a design doc or issue plan and preview what @{miniUsername} is likely to
          block, question, or keep private before you request review.
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-1.5">
            <label
              htmlFor="artifact-type"
              className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground"
            >
              Artifact type
            </label>
            <select
              id="artifact-type"
              value={artifactType}
              onChange={(event) => setArtifactType(event.target.value as ArtifactReviewType)}
              className="h-9 w-full appearance-none rounded-md border border-input bg-background px-3 text-sm ring-offset-background transition-colors hover:border-ring/50 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 dark:border-input dark:bg-input/30"
            >
              {ARTIFACT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="artifact-title"
              className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground"
            >
              Title
            </label>
            <Input
              id="artifact-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Design doc for retry isolation"
              maxLength={500}
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="artifact-body"
              className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground"
            >
              Body markdown
            </label>
            <Textarea
              id="artifact-body"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder={"## Summary\n- scope\n- risks\n- validation"}
              className="min-h-40 font-mono text-sm leading-6"
              maxLength={50000}
            />
          </div>

          <Button type="submit" disabled={formInvalid} className="w-full">
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Reviewing draft
              </>
            ) : (
              "Review draft"
            )}
          </Button>
        </form>

        {error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        {result && (
          <div className="space-y-5 border-t border-border/60 pt-5">
            {unavailableReason ? (
              <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm leading-6 text-amber-900 dark:text-amber-200">
                Review prediction unavailable: {unavailableReason}. The gated state is expected
                when the live predictor is disabled; the response below is not a real review prediction.
              </div>
            ) : null}
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">
                  {formatLabel(result.artifact_summary?.artifact_type ?? artifactType)}
                </Badge>
                <Badge variant="outline">@{result.reviewer_username}</Badge>
                <Badge
                  className={cn("border", approvalTone(result.expressed_feedback.approval_state))}
                >
                  {formatLabel(result.expressed_feedback.approval_state)}
                </Badge>
              </div>
              <p className="text-sm font-medium text-foreground">
                {result.artifact_summary?.title ?? title}
              </p>
            </div>

            <section className="space-y-4">
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-foreground">Private assessment</h3>
                <p className="text-sm text-muted-foreground">
                  Confidence {Math.round(result.private_assessment.confidence * 100)}%
                </p>
              </div>

              <div className="space-y-4">
                {SIGNAL_SECTIONS.map((section) => (
                  <div key={section.key} className="space-y-2">
                    <h4 className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
                      {section.label}
                    </h4>
                    <SignalList
                      signals={result.private_assessment[section.key]}
                      empty={section.empty}
                      outcomeMap={outcomeMap}
                      onOutcomeChange={handleOutcomeChange}
                      showOutcome={isOwner && !outcomeSaved}
                    />
                  </div>
                ))}
              </div>
            </section>

            <section className="space-y-3">
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-foreground">Expressed feedback</h3>
                <p className="text-sm leading-6 text-muted-foreground">
                  {result.expressed_feedback.summary}
                </p>
              </div>

              <div className="space-y-3">
                {result.expressed_feedback.comments.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No explicit comments returned.</p>
                ) : (
                  result.expressed_feedback.comments.map((comment, index) => (
                    <div
                      key={`${comment.issue_key ?? comment.type}-${index}`}
                      className="rounded-lg border border-border/60 bg-background/60 p-3"
                    >
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="outline">{comment.type}</Badge>
                        <Badge variant="outline">{formatLabel(comment.disposition)}</Badge>
                        {comment.issue_key && <Badge variant="outline">{comment.issue_key}</Badge>}
                      </div>
                      <p className="mt-3 text-sm font-medium text-foreground">{comment.summary}</p>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        {comment.rationale}
                      </p>
                    </div>
                  ))
                )}
              </div>
            </section>

            {/* Outcome capture — owner-only, shown after review result */}
            {isOwner && !outcomeSaved && (
              <section className="space-y-3 rounded-lg border border-border/60 bg-muted/20 p-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-foreground">Capture outcomes</h3>
                  {capturedCount > 0 && (
                    <span className="text-xs text-muted-foreground">
                      {capturedCount} / {allSignals.length} marked
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  What did you actually do with each suggestion? This trains the predictor.
                </p>

                <div className="space-y-2">
                  <label
                    htmlFor="artifact-disposition"
                    className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground"
                  >
                    Artifact final disposition
                  </label>
                  <div className="relative">
                    <select
                      id="artifact-disposition"
                      value={artifactDisposition}
                      onChange={(e) => setArtifactDisposition(e.target.value)}
                      className="h-9 w-full appearance-none rounded-md border border-input bg-background px-3 pr-8 text-sm ring-offset-background transition-colors hover:border-ring/50 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 dark:border-input dark:bg-input/30"
                    >
                      <option value="">— not specified —</option>
                      {ARTIFACT_DISPOSITION_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                  </div>
                </div>

                <div className="space-y-2">
                  <label
                    htmlFor="reviewer-summary"
                    className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground"
                  >
                    Notes (optional)
                  </label>
                  <Textarea
                    id="reviewer-summary"
                    value={reviewerSummary}
                    onChange={(e) => setReviewerSummary(e.target.value)}
                    placeholder="What did you change, skip, or push back on?"
                    className="min-h-16 text-sm leading-6"
                    maxLength={2000}
                  />
                </div>

                {outcomeError && (
                  <div className="flex items-center gap-2 rounded border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                    <XCircle className="h-4 w-4 shrink-0" />
                    {outcomeError}
                  </div>
                )}

                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={handleSaveOutcome}
                  disabled={savingOutcome}
                >
                  {savingOutcome ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Saving outcomes
                    </>
                  ) : (
                    "Save outcomes"
                  )}
                </Button>
              </section>
            )}

            {isOwner && outcomeSaved && (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
                <CheckCircle2 className="h-4 w-4 shrink-0" />
                Outcomes saved — this will improve future predictions.
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
