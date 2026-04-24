import { type NextRequest, NextResponse } from "next/server";
import { SignJWT } from "jose";
import { auth } from "@/lib/auth-server";

// Allow large file uploads (100MB) and longer execution time through the proxy
export const maxDuration = 60;
export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const SERVICE_JWT_SECRET = process.env.SERVICE_JWT_SECRET || "dev-service-secret-change-in-production";
const INTERNAL_API_SECRET = process.env.INTERNAL_API_SECRET || "dev-internal-secret-change-in-production";
const TRUSTED_SERVICE_SECRET = process.env.TRUSTED_SERVICE_SECRET || "dev-trusted-service-secret-change-in-production";
const DEV_AUTH_BYPASS = process.env.DEV_AUTH_BYPASS === "true";
const GITHUB_TOKEN = process.env.GITHUB_TOKEN;

const DEV_SESSION = {
  user: {
    id: "dev-user-001",
    name: "alliecatowo",
    email: "dev@example.com",
    image: "https://github.com/alliecatowo.png",
  },
} as const;

/**
 * Resolve the real GitHub login (handle) from the OAuth session.
 *
 * Neon Auth / Better Auth fills `user.name` with the GitHub *display name*
 * (e.g. "Allison Coleman"), not the login handle (e.g. "alliecatowo").
 * The avatar URL is our reliable source:
 *
 *   - "https://github.com/{login}.png"                       → extract login directly
 *   - "https://avatars.githubusercontent.com/u/{id}?v=4"    → call GitHub API with numeric id
 *
 * Falls back to null if neither pattern matches or the API call fails.
 * The result is not cached here — the BFF cookie gate already makes sync a
 * one-shot per session (Max-Age=86400).
 */
async function resolveGithubLogin(imageUrl: string | null | undefined): Promise<string | null> {
  if (!imageUrl) return null;

  // Pattern 1: https://github.com/{login}.png  (used by dev-bypass session)
  const directMatch = imageUrl.match(/^https:\/\/github\.com\/([A-Za-z0-9][A-Za-z0-9-]{0,38})\.png/);
  if (directMatch) return directMatch[1];

  // Pattern 2: https://avatars.githubusercontent.com/u/{numericId}
  const avatarMatch = imageUrl.match(/^https:\/\/avatars\.githubusercontent\.com\/u\/(\d+)/);
  if (!avatarMatch) return null;

  const githubUserId = avatarMatch[1];
  try {
    const headers: Record<string, string> = {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "minis-bff/1.0",
    };
    if (GITHUB_TOKEN) headers["Authorization"] = `Bearer ${GITHUB_TOKEN}`;

    const res = await fetch(`https://api.github.com/user/${githubUserId}`, { headers });
    if (!res.ok) {
      console.warn(`[proxy] GitHub API /user/${githubUserId} returned ${res.status}`);
      return null;
    }
    const data = await res.json() as { login?: string };
    return data.login ?? null;
  } catch (e) {
    console.warn("[proxy] Failed to resolve GitHub login:", e);
    return null;
  }
}

async function createServiceJwt(backendUserId: string, githubUsername?: string | null): Promise<string> {
  const secret = new TextEncoder().encode(SERVICE_JWT_SECRET);
  const claims: Record<string, unknown> = { sub: backendUserId };
  if (githubUsername) claims.github_username = githubUsername;
  return new SignJWT(claims)
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime("5m")
    .setIssuer("minis-bff")
    .sign(secret);
}

/**
 * Sync the authenticated user to the backend (idempotent upsert).
 * Returns the resolved github_username if sync succeeded, null on failure.
 */
async function syncUserToBackend(
  session: { user: { id: string; name?: string | null; email?: string | null; image?: string | null } },
): Promise<string | null> {
  const userId = session.user.id;

  // Resolve the GitHub *login* handle from the avatar URL.
  // session.user.name is the display name ("Allison Coleman"), not the handle ("alliecatowo").
  const githubLogin = await resolveGithubLogin(session.user.image);
  if (!githubLogin) {
    console.warn(`[proxy] Could not resolve GitHub login for user ${userId} (image=${session.user.image}); skipping sync`);
    return null;
  }

  try {
    const syncRes = await fetch(new URL("/api/auth/sync", BACKEND_URL), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Internal-Secret": INTERNAL_API_SECRET,
      },
      body: JSON.stringify({
        neon_auth_id: userId,
        github_username: githubLogin,
        display_name: session.user.name ?? null,
        avatar_url: session.user.image ?? null,
        email: session.user.email ?? null,
      }),
    });

    if (syncRes.ok) {
      const data = await syncRes.json() as { user_id: string; github_username?: string | null };
      console.log(`[proxy] User synced to backend: ${userId} github=${data.github_username}`);
      return data.github_username ?? githubLogin;
    }

    console.error(`[proxy] User sync returned ${syncRes.status}: ${await syncRes.text()}`);
    return null;
  } catch (e) {
    console.error("[proxy] User sync failed:", e);
    return null;
  }
}

/** Append the __minis_synced cookie to a Response so we skip sync on subsequent requests. */
function setSyncCookie(res: Response, userId: string): void {
  res.headers.append(
    "Set-Cookie",
    `__minis_synced=${userId}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400`,
  );
}

/**
 * Set a non-HttpOnly __minis_github cookie so client-side JS can read the resolved
 * GitHub login handle without an extra round-trip.  This is NOT sensitive — it is the
 * user's own public GitHub username, and the cookie is scoped to the same origin.
 */
function setGithubCookie(res: Response, githubUsername: string): void {
  res.headers.append(
    "Set-Cookie",
    `__minis_github=${encodeURIComponent(githubUsername)}; Path=/; SameSite=Lax; Max-Age=86400`,
  );
}

async function proxyRequest(req: NextRequest, params: { path: string[] }): Promise<Response> {
  const path = params.path.join("/");

  // Dev auth bypass: use a hard-coded dev session instead of Neon Auth
  let session: { user: { id: string; name?: string | null; email?: string | null; image?: string | null } } | null = null;
  if (DEV_AUTH_BYPASS) {
    session = DEV_SESSION;
    console.log(`[proxy] ${req.method} /api/${path} DEV_AUTH_BYPASS=true`);
  } else {
    const { data } = await auth.getSession();
    session = data as typeof session;
  }
  const backendUserId = session?.user?.id;
  console.log(`[proxy] ${req.method} /api/${path} hasAuth=${!!backendUserId}`);

  // Debug endpoint
  if (path === "_debug/auth") {
    return NextResponse.json({
      hasSession: !!session,
      backendUserId: backendUserId ?? null,
      hasBackendUrl: !!process.env.BACKEND_URL,
      backendUrl: process.env.BACKEND_URL?.substring(0, 20),
      cookies: req.cookies.getAll().map(c => c.name),
    });
  }

  // Sync authenticated user to backend (idempotent upsert, cookie-cached)
  let needsSyncCookie = false;
  // resolvedGithubUsername is set when sync just ran; used to include in JWT + public cookie.
  let resolvedGithubUsername: string | null = null;
  if (backendUserId && session?.user) {
    const wasSyncedBefore = req.cookies.get("__minis_synced")?.value === backendUserId;
    if (!wasSyncedBefore) {
      const syncedUsername = await syncUserToBackend(session as { user: { id: string; name?: string | null; email?: string | null; image?: string | null } });
      if (syncedUsername) {
        needsSyncCookie = true;
        resolvedGithubUsername = syncedUsername;
      }
    } else {
      // Already synced — recover the handle from the existing cookie (if set).
      const existingGithubCookie = req.cookies.get("__minis_github")?.value;
      if (existingGithubCookie) resolvedGithubUsername = decodeURIComponent(existingGithubCookie);
    }
  }

  // For dev bypass: use the hardcoded handle.
  if (DEV_AUTH_BYPASS && backendUserId) {
    resolvedGithubUsername = DEV_SESSION.user.name;
  }

  const url = new URL(`/api/${path}`, BACKEND_URL);

  // Forward query parameters
  req.nextUrl.searchParams.forEach((value, key) => {
    url.searchParams.set(key, value);
  });

  // Build headers, forwarding content-type and other relevant headers
  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) {
    headers.set("content-type", contentType);
  }

  // Add service JWT from Neon Auth session (BFF pattern)
  if (backendUserId) {
    const serviceJwt = await createServiceJwt(backendUserId, resolvedGithubUsername);
    headers.set("authorization", `Bearer ${serviceJwt}`);
  }

  // Inject trusted service secret for owner-facing review-cycle mutation paths.
  // These paths are already gated behind user auth above; the secret is server-side only.
  if (path.includes("minis/trusted/") && backendUserId) {
    headers.set("x-trusted-service-secret", TRUSTED_SERVICE_SECRET);
  }

  // Get request body for non-GET requests
  let body: BodyInit | null = null;
  if (req.method !== "GET" && req.method !== "HEAD") {
    if (contentType?.includes("multipart/form-data")) {
      body = await req.blob();
      headers.delete("content-type");
      headers.set("content-type", contentType);
    } else {
      body = await req.text();
    }
  }

  try {
    const backendRes = await fetch(url.toString(), {
      method: req.method,
      headers,
      body,
    });

    // For SSE responses, stream them through
    const resContentType = backendRes.headers.get("content-type") || "";
    if (resContentType.includes("text/event-stream")) {
      const sseRes = new Response(backendRes.body, {
        status: backendRes.status,
        headers: {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          connection: "keep-alive",
        },
      });
      if (needsSyncCookie) {
        setSyncCookie(sseRes, backendUserId!);
        if (resolvedGithubUsername) setGithubCookie(sseRes, resolvedGithubUsername);
      }
      return sseRes;
    }

    const responseHeaders = new Headers();
    backendRes.headers.forEach((value, key) => {
      if (!["transfer-encoding", "content-encoding", "content-length", "connection", "keep-alive"].includes(key.toLowerCase())) {
        responseHeaders.set(key, value);
      }
    });

    // 204 No Content has no body — don't try to read one
    if (backendRes.status === 204) {
      const noContentRes = new NextResponse(null, { status: 204, headers: responseHeaders });
      if (needsSyncCookie) {
        setSyncCookie(noContentRes, backendUserId!);
        if (resolvedGithubUsername) setGithubCookie(noContentRes, resolvedGithubUsername);
      }
      return noContentRes;
    }

    const resBody = await backendRes.arrayBuffer();
    const res = new NextResponse(resBody, {
      status: backendRes.status,
      headers: responseHeaders,
    });
    if (needsSyncCookie) {
      setSyncCookie(res, backendUserId!);
      if (resolvedGithubUsername) setGithubCookie(res, resolvedGithubUsername);
    }
    return res;
  } catch (err) {
    console.error("Proxy error:", err);
    return NextResponse.json(
      { detail: "Backend unavailable" },
      { status: 502 },
    );
  }
}

export async function GET(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyRequest(req, params);
}

export async function POST(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyRequest(req, params);
}

export async function PUT(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyRequest(req, params);
}

export async function DELETE(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyRequest(req, params);
}

export async function PATCH(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const params = await context.params;
  return proxyRequest(req, params);
}
