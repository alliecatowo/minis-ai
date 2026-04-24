"use client";

import { type FormEvent, useState } from "react";
import { Loader2 } from "lucide-react";
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
  type ArtifactReviewResponse,
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

function SignalList({
  signals,
  empty,
}: {
  signals: ReviewPredictionSignal[];
  empty: string;
}) {
  if (signals.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }

  return (
    <div className="space-y-3">
      {signals.map((signal) => (
        <div
          key={signal.key}
          className="rounded-lg border border-border/60 bg-background/60 p-3"
        >
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-medium text-foreground">{signal.summary}</p>
            <Badge variant="outline" className="shrink-0 text-[10px] uppercase">
              {Math.round(signal.confidence * 100)}%
            </Badge>
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">{signal.rationale}</p>
        </div>
      ))}
    </div>
  );
}

export function DraftReviewPanel({
  miniId,
  miniUsername,
}: {
  miniId: string;
  miniUsername: string;
}) {
  const [artifactType, setArtifactType] = useState<ArtifactReviewType>("design_doc");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [result, setResult] = useState<ArtifactReviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const formInvalid = title.trim().length === 0 || body.trim().length === 0 || submitting;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setResult(null);

    try {
      const nextResult = await reviewArtifact(miniId, {
        artifact_type: artifactType,
        title: title.trim(),
        artifact_summary: body.trim(),
      });
      setResult(nextResult);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to review artifact");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card className="mt-6 gap-4 border-border/60 bg-card/95 shadow-none">
      <CardHeader className="gap-1">
        <CardTitle className="text-base">Review a draft</CardTitle>
        <CardDescription className="leading-5">
          Submit a `design_doc` or `issue_plan` for @{miniUsername}. This calls{" "}
          <code className="font-mono text-[11px]">POST /api/minis/:id/artifact-review</code>{" "}
          through the frontend proxy. If that backend route is not deployed yet, submission will
          fail until it lands.
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
          </div>
        )}
      </CardContent>
    </Card>
  );
}
