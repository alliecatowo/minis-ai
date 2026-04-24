import { afterEach, describe, expect, it, vi } from "vitest";
import { reviewArtifact, type ArtifactReviewResponse } from "@/lib/api";

const MOCK_REVIEW_RESPONSE: ArtifactReviewResponse = {
  version: "review_prediction_v1",
  reviewer_username: "alliecatowo",
  repo_name: null,
  artifact_summary: {
    artifact_type: "design_doc",
    title: "Retry isolation",
  },
  private_assessment: {
    blocking_issues: [],
    non_blocking_issues: [],
    open_questions: [],
    positive_signals: [],
    confidence: 0.78,
  },
  delivery_policy: {
    author_model: "unknown",
    context: "normal",
    strictness: "medium",
    teaching_mode: true,
    shield_author_from_noise: true,
    rationale: "Default to direct but concise guidance.",
  },
  expressed_feedback: {
    summary: "Looks directionally right, but tighten rollback planning.",
    comments: [],
    approval_state: "comment",
  },
};

describe("reviewArtifact", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("posts artifact review requests to the frontend proxy", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(MOCK_REVIEW_RESPONSE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const response = await reviewArtifact("mini-123", {
      artifact_type: "design_doc",
      title: "Retry isolation",
      artifact_summary: "## Summary\n- isolate retries per worker",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/proxy/minis/mini-123/artifact-review",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    );

    const requestInit = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(requestInit.body))).toEqual({
      artifact_type: "design_doc",
      title: "Retry isolation",
      artifact_summary: "## Summary\n- isolate retries per worker",
    });
    expect(response).toEqual(MOCK_REVIEW_RESPONSE);
  });

  it("surfaces the unpublished-endpoint dependency clearly on 404", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Not Found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      reviewArtifact("mini-123", {
        artifact_type: "issue_plan",
        title: "Queue migration",
        artifact_summary: "## Plan\n- move workers",
      }),
    ).rejects.toThrow(
      "Artifact review endpoint unavailable. This UI depends on POST /api/minis/{id}/artifact-review.",
    );
  });
});
