import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DraftReviewPanel } from "@/components/draft-review-panel";
import { reviewArtifact, type ArtifactReviewResponse } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    reviewArtifact: vi.fn(),
  };
});

const reviewArtifactMock = vi.mocked(reviewArtifact);

const MOCK_REVIEW_RESPONSE: ArtifactReviewResponse = {
  version: "review_prediction_v1",
  reviewer_username: "alliecatowo",
  repo_name: null,
  artifact_summary: {
    artifact_type: "issue_plan",
    title: "Queue retry rollout",
  },
  private_assessment: {
    blocking_issues: [
      {
        key: "missing-rollback",
        summary: "Rollback path is underspecified.",
        rationale: "The plan changes queue semantics but does not define how to back out safely.",
        confidence: 0.91,
        evidence: [{ source: "input", detail: "No rollback section in markdown." }],
      },
    ],
    non_blocking_issues: [],
    open_questions: [],
    positive_signals: [
      {
        key: "good-observability",
        summary: "Observability gets first-class treatment.",
        rationale: "The draft calls out metrics and alerting before migration.",
        confidence: 0.74,
        evidence: [{ source: "input", detail: "Metrics and alerts are listed in the plan." }],
      },
    ],
    confidence: 0.84,
  },
  delivery_policy: {
    author_model: "unknown",
    context: "normal",
    strictness: "medium",
    teaching_mode: true,
    shield_author_from_noise: true,
    rationale: "Keep the feedback direct and focused on reviewer-visible risk.",
  },
  expressed_feedback: {
    summary: "Tighten the rollback section before asking for review.",
    comments: [
      {
        type: "blocker",
        disposition: "request_changes",
        issue_key: "missing-rollback",
        summary: "Add an explicit rollback sequence.",
        rationale: "Reviewers will block on migration work that cannot be unwound cleanly.",
      },
    ],
    approval_state: "request_changes",
  },
};

describe("DraftReviewPanel", () => {
  beforeEach(() => {
    reviewArtifactMock.mockReset();
  });

  it("submits draft markdown and renders the returned assessment", async () => {
    reviewArtifactMock.mockResolvedValue(MOCK_REVIEW_RESPONSE);

    render(<DraftReviewPanel miniId="mini-123" miniUsername="alliecatowo" />);

    fireEvent.change(screen.getByLabelText("Artifact type"), {
      target: { value: "issue_plan" },
    });
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Queue retry rollout" },
    });
    fireEvent.change(screen.getByLabelText("Body markdown"), {
      target: { value: "## Plan\n- migrate workers\n- add alerts" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review draft" }));

    await waitFor(() =>
      expect(reviewArtifactMock).toHaveBeenCalledWith("mini-123", {
        artifact_type: "issue_plan",
        title: "Queue retry rollout",
        artifact_summary: "## Plan\n- migrate workers\n- add alerts",
      }),
    );

    expect(await screen.findByText("Private assessment")).toBeInTheDocument();
    expect(screen.getByText("Rollback path is underspecified.")).toBeInTheDocument();
    expect(screen.getByText("Observability gets first-class treatment.")).toBeInTheDocument();
    expect(screen.getByText("Expressed feedback")).toBeInTheDocument();
    expect(
      screen.getByText("Tighten the rollback section before asking for review."),
    ).toBeInTheDocument();
    expect(screen.getByText("Add an explicit rollback sequence.")).toBeInTheDocument();
  });

  it("shows the dependency error when the endpoint is unavailable", async () => {
    reviewArtifactMock.mockRejectedValue(
      new Error(
        "Artifact review endpoint unavailable. This UI depends on POST /api/minis/{id}/artifact-review.",
      ),
    );

    render(<DraftReviewPanel miniId="mini-123" miniUsername="alliecatowo" />);

    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Queue retry rollout" },
    });
    fireEvent.change(screen.getByLabelText("Body markdown"), {
      target: { value: "## Plan\n- migrate workers\n- add alerts" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Review draft" }));

    expect(
      await screen.findByText(
        "Artifact review endpoint unavailable. This UI depends on POST /api/minis/{id}/artifact-review.",
      ),
    ).toBeInTheDocument();
  });
});
