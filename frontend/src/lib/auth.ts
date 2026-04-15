'use client';

import { createAuthClient } from '@neondatabase/auth/next';
import { useMemo } from 'react';

export const authClient = createAuthClient();

export interface AuthUser {
  id: string;
  github_username: string;
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

export function useAuth(): AuthContextType {
  const { data: session, isPending } = authClient.useSession();

  const user = useMemo<AuthUser | null>(() => {
    // Dev bypass: return mock user without Neon Auth session
    if (DEV_AUTH_BYPASS) return DEV_USER;
    if (!session?.user) return null;
    return {
      id: session.user.id ?? '',
      github_username: session.user.name ?? '',
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
