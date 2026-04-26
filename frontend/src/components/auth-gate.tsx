"use client";

import { type ReactNode } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";
import { Github, type LucideIcon } from "lucide-react";

interface AuthGateProps {
  children: ReactNode;
  icon: LucideIcon;
  message: string;
  title?: string;
  actionLabel?: string;
  secondaryHref?: string;
  secondaryLabel?: string;
}

export function AuthGate({
  children,
  icon: Icon,
  message,
  title = "Sign in required",
  actionLabel = "Sign in with GitHub",
  secondaryHref,
  secondaryLabel,
}: AuthGateProps) {
  const { user, loading: authLoading, login } = useAuth();

  if (authLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Skeleton className="h-8 w-48" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center px-4">
        <div className="w-full max-w-md rounded-2xl border border-border/60 bg-card/95 p-6 text-center shadow-2xl shadow-black/20">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full border border-chart-1/20 bg-chart-1/10">
            <Icon className="h-7 w-7 text-chart-1" />
          </div>
          <div className="mt-5">
            <p className="font-medium text-foreground">{title}</p>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{message}</p>
          </div>
          <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
            <Button onClick={login} size="sm" className="gap-1.5">
              <Github className="h-3.5 w-3.5" />
              {actionLabel}
            </Button>
            {secondaryHref && secondaryLabel && (
              <Button asChild size="sm" variant="outline">
                <Link href={secondaryHref}>{secondaryLabel}</Link>
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
