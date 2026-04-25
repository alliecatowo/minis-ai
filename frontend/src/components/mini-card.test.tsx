import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MiniCard } from "@/components/mini-card";
import type { Mini } from "@/lib/api";

function mini(overrides: Partial<Mini> = {}): Mini {
  return {
    id: "mini-1",
    username: "octocat",
    owner_id: null,
    visibility: "public",
    display_name: "Octo Cat",
    avatar_url: "https://github.com/octocat.png",
    bio: "Builds careful developer tools.",
    spirit_content: "",
    system_prompt: "",
    values: [{ name: "Reliability", description: "Prefers safe changes.", intensity: 0.9 }],
    status: "ready",
    sources_used: ["github", "claude_code"],
    created_at: "2026-04-25T00:00:00Z",
    ...overrides,
  };
}

describe("MiniCard", () => {
  it("opens ready minis directly in chat with evidence source badges", () => {
    render(<MiniCard mini={mini()} />);

    expect(screen.getByRole("link", { name: "Open chat for @octocat" })).toHaveAttribute(
      "href",
      "/m/octocat",
    );
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Open chat")).toBeInTheDocument();
    expect(screen.getByText("github")).toBeInTheDocument();
    expect(screen.getByText("claude code")).toBeInTheDocument();
    expect(screen.getByText("Reliability")).toBeInTheDocument();
  });

  it("routes processing and failed minis back to the build flow with clear actions", () => {
    const { rerender } = render(
      <MiniCard mini={mini({ status: "processing", sources_used: "github,blog" })} />,
    );

    expect(screen.getByRole("link", { name: "View progress for @octocat" })).toHaveAttribute(
      "href",
      "/create?username=octocat",
    );
    expect(screen.getByText("Building")).toBeInTheDocument();
    expect(screen.getByText("View progress")).toBeInTheDocument();
    expect(screen.getByText("blog")).toBeInTheDocument();

    rerender(<MiniCard mini={mini({ status: "failed" })} />);

    expect(screen.getByRole("link", { name: "Retry analysis for @octocat" })).toHaveAttribute(
      "href",
      "/create?username=octocat&regenerate=true",
    );
    expect(screen.getByText("Needs retry")).toBeInTheDocument();
    expect(screen.getByText("Retry analysis")).toBeInTheDocument();
  });
});
