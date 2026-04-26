"use client";

import { useEffect, useState, type ReactNode } from "react";

import { TosDialog } from "@/components/tos-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { TOS_VERSION } from "@/lib/constants";
import { useAuth } from "@/lib/auth";

interface MeResponse {
  tos_version_accepted: string | null;
}

export function TosGate({ children }: { children: ReactNode }) {
  const { user, loading: authLoading, logout } = useAuth();
  const [checking, setChecking] = useState(false);
  const [needsAcceptance, setNeedsAcceptance] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!user) {
      setNeedsAcceptance(false);
      return;
    }

    let active = true;
    setChecking(true);
    void fetch("/api/proxy/auth/me", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) return { tos_version_accepted: null } as MeResponse;
        return (await response.json()) as MeResponse;
      })
      .then((data) => {
        if (!active) return;
        setNeedsAcceptance(data.tos_version_accepted !== TOS_VERSION);
      })
      .catch(() => {
        if (active) setNeedsAcceptance(true);
      })
      .finally(() => {
        if (active) setChecking(false);
      });

    return () => {
      active = false;
    };
  }, [user]);

  const acceptTos = async () => {
    setSaving(true);
    try {
      const response = await fetch("/api/proxy/auth/accept-tos", { method: "POST" });
      if (response.ok) {
        setNeedsAcceptance(false);
      }
    } finally {
      setSaving(false);
    }
  };

  if (authLoading || (user && checking)) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Skeleton className="h-8 w-48" />
      </div>
    );
  }

  return (
    <>
      {children}
      {user && (
        <TosDialog
          open={needsAcceptance}
          onOpenChange={() => undefined}
          title="Updated Terms Required"
          description="You need to accept the latest Terms of Service before continuing."
          onAgree={acceptTos}
          onCancel={logout}
          loading={saving}
        />
      )}
    </>
  );
}
