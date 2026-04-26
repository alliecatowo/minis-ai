import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PipelineProgress } from "@/components/pipeline-progress";

describe("PipelineProgress", () => {
  it("maps backend explore events onto the visible model-building step", () => {
    render(
      <PipelineProgress
        currentStep="explore"
        message="Exploring GitHub evidence..."
        progress={40}
      />,
    );

    expect(screen.getByText("Fetching evidence")).toBeInTheDocument();
    expect(screen.getByText("Exploring judgment")).toBeInTheDocument();
    expect(
      screen.getByText("Extracting values, heuristics, and recurring review behavior."),
    ).toBeInTheDocument();
    expect(screen.getByText("Exploring GitHub evidence...")).toBeInTheDocument();
  });

  it("keeps legacy fetching/extracting labels active instead of dropping all stages", () => {
    const { rerender } = render(
      <PipelineProgress currentStep="fetching" message="Starting..." progress={0} />,
    );

    expect(screen.getByText("Fetching evidence")).toHaveClass("font-medium");

    rerender(
      <PipelineProgress
        currentStep="extract"
        message="Extracting values..."
        progress={35}
      />,
    );

    expect(screen.getByText("Exploring judgment")).toHaveClass("font-medium");
  });
});
