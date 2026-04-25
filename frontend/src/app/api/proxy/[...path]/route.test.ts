import { NextRequest } from "next/server";
import { TextEncoder } from "node:util";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authMock = vi.hoisted(() => ({
  getSession: vi.fn(),
}));

vi.mock("@/lib/auth-server", () => ({
  auth: authMock,
}));

vi.mock("jose", () => ({
  SignJWT: class {
    setProtectedHeader() {
      return this;
    }
    setIssuedAt() {
      return this;
    }
    setExpirationTime() {
      return this;
    }
    setIssuer() {
      return this;
    }
    async sign() {
      return "browser-service-jwt";
    }
  },
}));

describe("backend proxy trusted-service boundary", () => {
  beforeEach(() => {
    vi.stubGlobal("TextEncoder", TextEncoder);
    vi.stubEnv("BACKEND_URL", "https://backend.test");
    vi.stubEnv("SERVICE_JWT_SECRET", "test-service-secret-change-in-production");
    vi.stubEnv("INTERNAL_API_SECRET", "test-internal-secret-change-in-production");
    vi.stubEnv("TRUSTED_SERVICE_SECRET", "test-trusted-secret");
    authMock.getSession.mockResolvedValue({
      data: {
        user: {
          id: "attacker-user",
          name: "Attacker",
          email: "attacker@example.test",
          image: "https://github.com/attacker.png",
        },
      },
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("does not inject the trusted-service secret into browser-originated trusted route requests", async () => {
    const backendCalls: Array<{ url: string; init?: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: string | URL | Request, init?: RequestInit) => {
        const url = input.toString();
        backendCalls.push({ url, init });

        if (url === "https://backend.test/api/auth/sync") {
          return new Response(
            JSON.stringify({ user_id: "attacker-user", github_username: "attacker" }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }

        return new Response(JSON.stringify({ detail: "Unauthorized" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      },
    );

    const { PUT } = await import("./route");
    const request = new NextRequest(
      "http://localhost/api/proxy/minis/trusted/victim-mini/review-cycles",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ external_id: "attacker-write" }),
      },
    );

    const response = await PUT(request, {
      params: Promise.resolve({
        path: ["minis", "trusted", "victim-mini", "review-cycles"],
      }),
    });

    const trustedCall = backendCalls.find((call) =>
      call.url === "https://backend.test/api/minis/trusted/victim-mini/review-cycles",
    );
    expect(trustedCall).toBeDefined();

    const headers = new Headers(trustedCall?.init?.headers);
    expect(headers.has("authorization")).toBe(true);
    expect(headers.has("x-trusted-service-secret")).toBe(false);
    expect(response.status).toBe(401);
  });
});
