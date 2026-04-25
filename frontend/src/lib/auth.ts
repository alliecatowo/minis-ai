'use client';

import { createAuthClient } from '@neondatabase/auth/next';
import { useMemo } from 'react';

export const authClient = createAuthClient();

export interface AuthUser {
  id: string;
  github_username: string | null;
  display_name: string | null;
  avatar_url: string | null;
}

export interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  login: () => void;
  logout: () => void;
}

const DEV_AUTH_BYPASS = process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS === 'true';

const DEV_USER: AuthUser = {
  id: 'dev-user-001',
  github_username: 'alliecatowo',
  display_name: 'Dev User',
  avatar_url: 'https://github.com/alliecatowo.png',
};

/**
 * Read the __minis_github cookie set by the BFF after /api/auth/sync.
 * This cookie is NOT HttpOnly, so client JS can read it directly.
 * It holds the real GitHub login handle (e.g. "alliecatowo"), NOT the display name.
 * Returns empty string if the cookie is absent or document is unavailable (SSR).
 */
function readGithubCookie(): string {
  if (typeof document === 'undefined') return '';
  const match = document.cookie
    .split('; ')
    .find(row => row.startsWith('__minis_github='));
  if (!match) return '';
  return decodeURIComponent(match.split('=')[1] ?? '');
}

export function useAuth(): AuthContextType {
  const { data: session, isPending } = authClient.useSession();

  const user = useMemo<AuthUser | null>(() => {
    // Dev bypass: return mock user without Neon Auth session
    if (DEV_AUTH_BYPASS) return DEV_USER;
    if (!session?.user) return null;

    // The BFF sets __minis_github after resolving the real GitHub login handle
    // via the GitHub API during /api/auth/sync.  Prefer this over session.user.name,
    // which is the OAuth display name (e.g. "Allison Coleman") — not the handle.
    const githubHandle = readGithubCookie() || null;

    return {
      id: session.user.id ?? '',
      github_username: githubHandle,
      display_name: session.user.name ?? null,
      avatar_url: session.user.image ?? null,
    };
  }, [session]);

  return {
    user,
    token: null,
    // When bypass is active, never show loading state
    loading: DEV_AUTH_BYPASS ? false : isPending,
    login: DEV_AUTH_BYPASS
      ? () => console.log('[dev] DEV_AUTH_BYPASS is enabled — login is a no-op')
      : () => authClient.signIn.social({ provider: 'github', callbackURL: '/' }),
    logout: DEV_AUTH_BYPASS
      ? () => console.log('[dev] DEV_AUTH_BYPASS is enabled — logout is a no-op')
      : () => authClient.signOut(),
  };
}
