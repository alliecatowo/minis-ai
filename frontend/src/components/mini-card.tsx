"use client";

import Link from "next/link";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { Mini } from "@/lib/api";
import { ArrowRight, Loader2, RotateCcw } from "lucide-react";

const statusColors: Record<Mini["status"], string> = {
  pending: "bg-yellow-500/20 text-yellow-400",
  processing: "bg-blue-500/20 text-blue-400",
  ready: "bg-emerald-500/20 text-emerald-400",
  failed: "bg-red-500/20 text-red-400",
};

const statusCopy: Record<
  Mini["status"],
  { label: string; description: string; action: string }
> = {
  pending: {
    label: "Queued",
    description: "Analysis is waiting to start.",
    action: "Resume setup",
  },
  processing: {
    label: "Building",
    description: "Evidence is still being explored.",
    action: "View progress",
  },
  ready: {
    label: "Ready",
    description: "Open the mini and ask for predicted review feedback.",
    action: "Open chat",
  },
  failed: {
    label: "Needs retry",
    description: "Creation failed before a usable result was saved.",
    action: "Retry analysis",
  },
};

function normalizeSources(sources: Mini["sources_used"]): string[] {
  if (Array.isArray(sources)) return sources.filter(Boolean);
  if (typeof sources === "string" && sources.trim()) {
    return sources
      .split(",")
      .map((source) => source.trim())
      .filter(Boolean);
  }
  return [];
}

function cardHref(mini: Mini): string {
  if (mini.status === "ready") return `/m/${mini.username}`;
  const params = new URLSearchParams({ username: mini.username });
  if (mini.status === "failed") params.set("regenerate", "true");
  return `/create?${params.toString()}`;
}

export function MiniCard({ mini }: { mini: Mini }) {
  const copy = statusCopy[mini.status];
  const sources = normalizeSources(mini.sources_used);

  return (
    <Link href={cardHref(mini)} aria-label={`${copy.action} for @${mini.username}`}>
      <Card className="group cursor-pointer border-border/50 transition-all duration-200 hover:border-border hover:bg-card/80 hover:shadow-lg hover:shadow-black/5">
        <CardHeader className="flex-row items-center gap-3">
          <Avatar className="h-10 w-10">
            <AvatarImage src={mini.avatar_url} alt={mini.username} />
            <AvatarFallback className="font-mono text-xs">
              {mini.username.slice(0, 2).toUpperCase()}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate font-mono text-sm font-medium">
                {mini.display_name || mini.username}
              </span>
              <Badge
                variant="secondary"
                className={`shrink-0 text-[10px] ${statusColors[mini.status]}`}
              >
                {copy.label}
              </Badge>
            </div>
            <p className="truncate font-mono text-xs text-muted-foreground">
              @{mini.username}
            </p>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="line-clamp-2 text-sm text-muted-foreground">
            {mini.bio || "No bio yet."}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {sources.slice(0, 3).map((source) => (
              <Badge
                key={source}
                variant="secondary"
                className="border-border/50 bg-secondary/50 font-mono text-[10px] text-muted-foreground"
              >
                {source.replaceAll("_", " ")}
              </Badge>
            ))}
            {mini.values?.slice(0, 3).map((v) => (
              <Badge key={v.name} variant="outline" className="text-[10px]">
                {v.name}
              </Badge>
            ))}
          </div>
          <div className="flex items-center justify-between rounded-lg border border-border/40 bg-secondary/20 px-3 py-2">
            <div className="min-w-0">
              <p className="text-xs font-medium text-foreground">{copy.action}</p>
              <p className="truncate text-[11px] text-muted-foreground">
                {copy.description}
              </p>
            </div>
            {mini.status === "processing" ? (
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-400" />
            ) : mini.status === "failed" ? (
              <RotateCcw className="h-3.5 w-3.5 shrink-0 text-red-400 transition-transform group-hover:-rotate-45" />
            ) : (
              <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            )}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
