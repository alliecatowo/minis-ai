import { NextRequest } from "next/server";
import { TextEncoder } from "node:util";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authMock = vi.hoisted(() => ({
  getSession: vi.fn(),
}));

const jwtMock = vi.hoisted(() => ({
  claims: [] as Array<Record<string, unknown>>,
}));

vi.mock("@/lib/auth-server", () => ({
  auth: authMock,
}));

vi.mock("jose", () => ({
  SignJWT: class {
    constructor(claims: Record<string, unknown>) {
      jwtMock.claims.push(claims);
    }
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
    jwtMock.claims = [];
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

  it("syncs the provider login from the GitHub avatar instead of session display name", async () => {
    authMock.getSession.mockResolvedValue({
      data: {
        user: {
          id: "user-123",
          name: "Mona Lisa",
          email: "mona@example.test",
          image: "https://github.com/octocat.png",
        },
      },
    });
    const backendCalls: Array<{ url: string; init?: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: string | URL | Request, init?: RequestInit) => {
        const url = input.toString();
        backendCalls.push({ url, init });

        if (url === "https://backend.test/api/auth/sync") {
          return new Response(
            JSON.stringify({ user_id: "user-123", github_username: "octocat" }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }

        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    );

    const { GET } = await import("./route");
    const request = new NextRequest("http://localhost/api/proxy/auth/me");

    const response = await GET(request, {
      params: Promise.resolve({ path: ["auth", "me"] }),
    });

    const syncCall = backendCalls.find((call) => call.url === "https://backend.test/api/auth/sync");
    expect(syncCall).toBeDefined();
    expect(JSON.parse(syncCall?.init?.body as string)).toMatchObject({
      neon_auth_id: "user-123",
      github_username: "octocat",
      display_name: "Mona Lisa",
    });
    expect(jwtMock.claims.at(-1)).toMatchObject({
      sub: "user-123",
      github_username: "octocat",
    });
    expect(response.headers.get("set-cookie") ?? "").toContain("__minis_github=octocat");
  });

  it("prefers stable provider login fields over display name and avatar fallback", async () => {
    authMock.getSession.mockResolvedValue({
      data: {
        user: {
          id: "user-provider-login",
          name: "The Octocat",
          username: "octocat",
          email: "octo@example.test",
          image: "https://example.test/not-github.png",
        },
      },
    });
    const backendCalls: Array<{ url: string; init?: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: string | URL | Request, init?: RequestInit) => {
        const url = input.toString();
        backendCalls.push({ url, init });

        if (url === "https://backend.test/api/auth/sync") {
          return new Response(
            JSON.stringify({ user_id: "user-provider-login", github_username: "octocat" }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }

        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    );

    const { GET } = await import("./route");
    const request = new NextRequest("http://localhost/api/proxy/auth/me");

    await GET(request, {
      params: Promise.resolve({ path: ["auth", "me"] }),
    });

    const syncCall = backendCalls.find((call) => call.url === "https://backend.test/api/auth/sync");
    expect(JSON.parse(syncCall?.init?.body as string)).toMatchObject({
      github_username: "octocat",
      display_name: "The Octocat",
    });
  });

  it("does not sync a display name as github_username when provider login cannot be resolved", async () => {
    authMock.getSession.mockResolvedValue({
      data: {
        user: {
          id: "user-456",
          name: "Display Name",
          email: "display@example.test",
          image: "https://example.test/avatar.png",
        },
      },
    });
    const backendCalls: Array<{ url: string; init?: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: string | URL | Request, init?: RequestInit) => {
        const url = input.toString();
        backendCalls.push({ url, init });
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    );

    const { GET } = await import("./route");
    const request = new NextRequest("http://localhost/api/proxy/auth/me");

    await GET(request, {
      params: Promise.resolve({ path: ["auth", "me"] }),
    });

    expect(backendCalls.some((call) => call.url === "https://backend.test/api/auth/sync")).toBe(false);
    expect(jwtMock.claims.at(-1)).toEqual({ sub: "user-456" });
  });

  it("uses the existing synced GitHub cookie without falling back to session display name", async () => {
    authMock.getSession.mockResolvedValue({
      data: {
        user: {
          id: "user-789",
          name: "Readable Human",
          email: "human@example.test",
          image: "https://example.test/avatar.png",
        },
      },
    });
    const backendCalls: Array<{ url: string; init?: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(
      async (input: string | URL | Request, init?: RequestInit) => {
        const url = input.toString();
        backendCalls.push({ url, init });
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    );

    const { GET } = await import("./route");
    const request = new NextRequest("http://localhost/api/proxy/auth/me", {
      headers: {
        Cookie: "__minis_synced=user-789; __minis_github=octocat",
      },
    });

    await GET(request, {
      params: Promise.resolve({ path: ["auth", "me"] }),
    });

    expect(backendCalls.some((call) => call.url === "https://backend.test/api/auth/sync")).toBe(false);
    expect(jwtMock.claims.at(-1)).toMatchObject({
      sub: "user-789",
      github_username: "octocat",
    });
  });
});
