import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Github } from "lucide-react";
import { AuthGate } from "@/components/auth-gate";
import { useAuth } from "@/lib/auth";

vi.mock("@/lib/auth", () => ({
  useAuth: vi.fn(),
}));

const useAuthMock = vi.mocked(useAuth);

describe("AuthGate", () => {
  it("renders the gated sign-in state with an optional demo link", () => {
    const login = vi.fn();
    useAuthMock.mockReturnValue({
      user: null,
      token: null,
      loading: false,
      login,
      logout: vi.fn(),
    });

    render(
      <AuthGate
        icon={Github}
        title="Sign in to build a review mini"
        message="GitHub sign-in keeps ownership and private source choices attached to your account."
        actionLabel="Continue with GitHub"
        secondaryHref="/m/alliecatowo"
        secondaryLabel="Try the demo"
      >
        <div>private app</div>
      </AuthGate>,
    );

    expect(screen.getByText("Sign in to build a review mini")).toBeInTheDocument();
    expect(screen.getByText(/private source choices/)).toBeInTheDocument();
    expect(screen.queryByText("private app")).toBeNull();
    expect(screen.getByRole("link", { name: "Try the demo" })).toHaveAttribute(
      "href",
      "/m/alliecatowo",
    );

    fireEvent.click(screen.getByRole("button", { name: /Continue with GitHub/ }));
    expect(login).toHaveBeenCalledOnce();
  });

  it("renders children once the user is authenticated", () => {
    useAuthMock.mockReturnValue({
      user: {
        id: "user-1",
        github_username: "octocat",
        display_name: "Octo Cat",
        avatar_url: null,
      },
      token: null,
      loading: false,
      login: vi.fn(),
      logout: vi.fn(),
    });

    render(
      <AuthGate icon={Github} message="Sign in first.">
        <div>private app</div>
      </AuthGate>,
    );

    expect(screen.getByText("private app")).toBeInTheDocument();
    expect(screen.queryByText("Sign in required")).toBeNull();
  });
});
