"use client";

import { useState } from "react";
import Link from "next/link";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { PersonalityRadar } from "@/components/personality-radar";
import { AgreementScorecardCard } from "@/components/chat/AgreementScorecardCard";
import {
  ArrowLeft,
  ChevronRight,
  Github,
  MessageSquare,
  Sparkles,
  Trash2,
} from "lucide-react";
import { type Mini } from "@/lib/api";

function parseSourcesUsed(sourcesUsed?: string | string[]): string[] {
  if (!sourcesUsed) return [];
  if (Array.isArray(sourcesUsed)) return sourcesUsed;
  try {
    const parsed = JSON.parse(sourcesUsed);
    if (Array.isArray(parsed)) return parsed;
  } catch {
    return sourcesUsed.split(",").map((s) => s.trim()).filter(Boolean);
  }
  return [];
}

function SidebarSection({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 py-1 text-xs font-medium uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground">
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 ${open ? "rotate-90" : ""}`}
        />
        {title}
      </CollapsibleTrigger>
      <CollapsibleContent className="overflow-hidden data-[state=open]:animate-collapsible-down data-[state=closed]:animate-collapsible-up">
        <div className="pt-3">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  );
}

interface MiniProfileProps {
  mini: Mini;
  isOwner: boolean;
  onDelete: () => Promise<void>;
  deleting: boolean;
}

export function MiniProfile({ mini, isOwner, onDelete, deleting }: MiniProfileProps) {
  const [deleteOpen, setDeleteOpen] = useState(false);

  const sources = parseSourcesUsed(mini.sources_used);
  const hasSkillsOrTraits =
    (mini.skills && mini.skills.length > 0) ||
    (mini.traits && mini.traits.length > 0);
  const hasRadar = mini.values && mini.values.length >= 3;

  const handleDelete = async () => {
    await onDelete();
    setDeleteOpen(false);
  };

  return (
    <div className="space-y-5">
      {/* Back to gallery */}
      <Link
        href="/gallery"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-3 w-3" />
        Back to gallery
      </Link>

      {/* Owner badge */}
      {isOwner && (
        <div className="space-y-3">
          <div className="flex items-center justify-between rounded-lg border border-chart-1/30 bg-chart-1/5 px-3 py-2">
            <div className="flex items-center gap-2">
              <Sparkles className="h-3.5 w-3.5 text-chart-1" />
              <span className="text-xs font-medium text-chart-1">This is your mini</span>
            </div>
            <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
              <DialogTrigger asChild>
                <button
                  className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  title="Delete mini"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Delete @{mini.username}?</DialogTitle>
                  <DialogDescription>
                    This will permanently delete this mini and all associated data.
                    This action cannot be undone.
                  </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <Button
                    variant="outline"
                    onClick={() => setDeleteOpen(false)}
                    disabled={deleting}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={handleDelete}
                    disabled={deleting}
                  >
                    {deleting ? "Deleting..." : "Delete"}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
          <AgreementScorecardCard key={mini.username} username={mini.username} />
        </div>
      )}

      {/* Identity */}
      <div className="flex items-start gap-4">
        <Avatar className="h-16 w-16 shrink-0">
          <AvatarImage src={mini.avatar_url} alt={mini.username} />
          <AvatarFallback className="font-mono text-lg">
            {mini.username.slice(0, 2).toUpperCase()}
          </AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold">
            {mini.display_name || mini.username}
          </h1>
          {mini.roles?.primary ? (
            <p className="text-sm text-muted-foreground">{mini.roles.primary}</p>
          ) : (
            <p className="font-mono text-sm text-muted-foreground">@{mini.username}</p>
          )}
        </div>
      </div>

      {/* Secondary roles */}
      {mini.roles?.secondary && mini.roles.secondary.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {mini.roles.secondary.map((role) => (
            <Badge key={role} variant="secondary" className="text-[11px]">
              {role}
            </Badge>
          ))}
        </div>
      )}

      {/* Bio */}
      {mini.bio && (
        <p className="text-sm leading-relaxed text-muted-foreground">{mini.bio}</p>
      )}

      <Separator />

      {/* Skills & Traits */}
      {hasSkillsOrTraits && (
        <>
          <SidebarSection title="Skills & Traits">
            <div className="space-y-3">
              {mini.skills && mini.skills.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {mini.skills.map((skill) => (
                    <Badge key={skill} variant="default" className="text-[11px]">
                      {skill}
                    </Badge>
                  ))}
                </div>
              )}
              {mini.traits && mini.traits.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {mini.traits.map((trait) => (
                    <Badge key={trait} variant="outline" className="text-[11px]">
                      {trait}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </SidebarSection>
          <Separator />
        </>
      )}

      {/* Personality Radar */}
      {hasRadar && (
        <>
          <SidebarSection title="Personality Radar">
            <PersonalityRadar values={mini.values} />
          </SidebarSection>
          <Separator />
        </>
      )}

      {/* Sources */}
      {sources.length > 0 && (
        <>
          <SidebarSection title="Sources">
            <div className="flex flex-wrap gap-1.5">
              {sources.map((source) => (
                <Badge key={source} variant="outline" className="gap-1 text-xs">
                  {source === "github" ? (
                    <Github className="h-3 w-3" />
                  ) : source === "claude_code" ? (
                    <MessageSquare className="h-3 w-3" />
                  ) : null}
                  {source === "github"
                    ? "GitHub"
                    : source === "claude_code"
                      ? "Claude Code"
                      : source}
                </Badge>
              ))}
            </div>
          </SidebarSection>
          <Separator />
        </>
      )}

      {/* Spirit Doc */}
      {mini.spirit_content && (
        <SidebarSection title="Spirit Doc">
          <div className="rounded-lg bg-secondary/30 p-4 text-sm text-muted-foreground whitespace-pre-wrap max-h-96 overflow-y-auto">
            {mini.spirit_content}
          </div>
        </SidebarSection>
      )}

      {/* Enhance with Claude Code CTA */}
      {isOwner && !sources.includes("claude_code") && (
        <Link
          href={`/create?username=${mini.username}&regenerate=true`}
          className="flex items-center gap-3 rounded-lg border border-dashed border-border/50 px-4 py-3 text-sm transition-colors hover:border-border hover:bg-secondary/30"
        >
          <MessageSquare className="h-4 w-4 text-muted-foreground" />
          <div>
            <p className="font-medium">Enhance with Claude Code</p>
            <p className="text-xs text-muted-foreground">
              Add conversation data for richer personality
            </p>
          </div>
        </Link>
      )}
    </div>
  );
}
