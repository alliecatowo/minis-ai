"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { MiniCard } from "@/components/mini-card";
import { listMinis, getPromoMini, type Mini } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  ArrowRight,
  Github,
  Users,
  Search,
  Bot,
  Wrench,
  MessageSquare,
  ShieldCheck,
  BarChart3,
  Sparkles,
} from "lucide-react";

const PROMO_MINI = process.env.NEXT_PUBLIC_PROMO_MINI || "alliecatowo";

function HeroInput() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [loadedAvatar, setLoadedAvatar] = useState<string | null>(null);
  const [loadedUsername, setLoadedUsername] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

  const avatarLoading = useMemo(() => {
    const trimmed = username.trim();
    return trimmed !== "" && trimmed !== loadedUsername && loadedAvatar !== `https://github.com/${trimmed}.png`;
  }, [username, loadedUsername, loadedAvatar]);

  const avatarUrl = useMemo(() => {
    if (!username.trim()) return null;
    return loadedAvatar;
  }, [username, loadedAvatar]);

  useEffect(() => {
    const trimmed = username.trim();
    if (!trimmed) {
      return;
    }

    const timeout = setTimeout(() => {
      const img = new Image();
      img.onload = () => {
        setLoadedAvatar(`https://github.com/${trimmed}.png`);
        setLoadedUsername(trimmed);
      };
      img.onerror = () => {
        setLoadedAvatar(null);
        setLoadedUsername("");
      };
      img.src = `https://github.com/${trimmed}.png`;
    }, 400);

    return () => clearTimeout(timeout);
  }, [username]);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!username.trim()) return;
      setSubmitting(true);
      router.push(`/create?username=${encodeURIComponent(username.trim())}`);
    },
    [username, router]
  );

  return (
    <form
      onSubmit={handleSubmit}
      className="mt-10 flex w-full max-w-md flex-col items-stretch gap-3 sm:flex-row sm:items-center"
    >
      <div className="relative flex-1">
        <div className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2">
          {avatarUrl ? (
            <Avatar className="h-6 w-6">
              <AvatarImage src={avatarUrl} alt={username} />
              <AvatarFallback className="text-[10px]">
                <Github className="h-3.5 w-3.5" />
              </AvatarFallback>
            </Avatar>
          ) : avatarLoading ? (
            <Skeleton className="h-6 w-6 rounded-full" />
          ) : (
            <Github className="h-4 w-4 text-muted-foreground" />
          )}
        </div>
        <Input
          type="text"
          placeholder="GitHub username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="h-12 pl-12 font-mono text-sm"
          autoFocus
        />
      </div>
      <Button
        type="submit"
        size="lg"
        disabled={!username.trim() || submitting}
        className="h-12 gap-1.5 sm:w-auto"
      >
        Create Review Mini
        <ArrowRight className="h-4 w-4" />
      </Button>
    </form>
  );
}

const steps = [
  {
    number: "1",
    title: "Pick the Reviewer",
    description: "Start with a GitHub username and choose the repos and evidence to include",
  },
  {
    number: "2",
    title: "Model Their Review Function",
    description: "Mine commits, pull requests, and review history to learn what they notice and block on",
  },
  {
    number: "3",
    title: "Run Pre-Review",
    description: "Ask what they would flag, soften, or ignore before the human review starts",
  },
];

const highlights = [
  {
    icon: Search,
    title: "Predictive Review",
    description: "See what a specific reviewer is likely to block on before you request review.",
  },
  {
    icon: MessageSquare,
    title: "Pre-Review Workflows",
    description: "Use the mini in chat and terminal flows to revise the change before the human reads it.",
  },
  {
    icon: BarChart3,
    title: "Agreement Metrics",
    description: "Track approval accuracy, blocker precision, and comment overlap against the eventual human review.",
  },
  {
    icon: ShieldCheck,
    title: "Preserved Judgment",
    description: "Model what the reviewer believes privately and what they would actually choose to say out loud.",
  },
  {
    icon: Bot,
    title: "Repo-Aware Evidence",
    description: "Ground predictions in PR history, repo conventions, and the source material behind real engineering calls.",
  },
  {
    icon: Wrench,
    title: "Fits Existing Work",
    description: "Keep humans in charge while bringing reviewer context into Claude Code, GitHub, and team workflows.",
  },
];

const scorecardMetrics = [
  {
    title: "Approval Accuracy",
    description: "Did the mini call approve, comment, or request changes the same way the human reviewer did?",
  },
  {
    title: "Blocker Precision",
    description: "Did it find the issues the reviewer would actually block on instead of spraying generic feedback?",
  },
  {
    title: "Comment Overlap",
    description: "How much of the eventual human review was predicted before the request went out?",
  },
];

function LandingPage() {
  const { login } = useAuth();
  const [minis, setMinis] = useState<Mini[]>([]);
  const [minisLoading, setMinisLoading] = useState(true);
  const [promoMini, setPromoMini] = useState<Mini | null>(null);
  const [promoLoaded, setPromoLoaded] = useState(false);

  useEffect(() => {
    listMinis()
      .then(setMinis)
      .catch(() => setMinis([]))
      .finally(() => setMinisLoading(false));
    getPromoMini()
      .then(setPromoMini)
      .finally(() => setPromoLoaded(true));
  }, []);

  const readyMinis = minis.filter((m) => m.status === "ready").slice(0, 6);

  return (
    <div className="flex flex-col items-center">
      {/* Hero */}
      <section className="flex w-full flex-col items-center px-4 pb-20 pt-24 text-center sm:pt-32">
        <h1 className="max-w-2xl text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
          Predict the{" "}
          <span className="bg-gradient-to-r from-chart-1 to-chart-2 bg-clip-text text-transparent">
            review
          </span>
          {" "}before you request it
        </h1>
        <p className="mt-4 max-w-2xl text-base text-muted-foreground sm:text-lg">
          Minis builds a repo-aware review model from commits, PRs, and review
          history so your team can pre-review work, measure agreement with the
          eventual human feedback, and preserve engineering judgment instead of
          flattening it into generic AI advice.
        </p>
        <p className="mt-2 text-sm font-medium text-chart-1 sm:text-base">
          Private assessment, delivery policy, and expressed feedback in one loop.
        </p>
        <HeroInput />
        <div className="mt-4 flex flex-col items-center gap-2 text-sm text-muted-foreground sm:flex-row">
          <span>Not ready to sign in?</span>
          <Link href={`/m/${PROMO_MINI}`} className="inline-flex items-center gap-1 font-medium text-foreground underline-offset-4 hover:underline">
            <Sparkles className="h-3.5 w-3.5 text-chart-2" />
            Try the live demo mini
          </Link>
        </div>
      </section>

      <section className="w-full border-t border-border/50 py-16">
        <div className="mx-auto max-w-6xl px-4">
          <div className="mb-8 text-center">
            <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
              Measured on agreement, not vibes
            </h2>
            <p className="mx-auto mt-3 max-w-2xl text-sm text-muted-foreground sm:text-base">
              The product claim is simple: predict how a specific engineer reviews novel work,
              then score the prediction against the human review that actually happens.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            {scorecardMetrics.map((metric) => (
              <Card key={metric.title} className="border-border/50">
                <CardContent className="pt-6">
                  <p className="font-mono text-xs uppercase tracking-[0.18em] text-chart-2">
                    Agreement Metric
                  </p>
                  <h3 className="mt-3 text-lg font-semibold">{metric.title}</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {metric.description}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* Try it — Promo Mini */}
      {promoLoaded && (
        <section className="w-full border-t border-border/50 py-16">
          <div className="mx-auto max-w-lg px-4">
            <Card className="overflow-hidden border-border/50">
              <CardContent className="flex flex-col items-center gap-4 pt-8 pb-8 text-center">
                {promoMini ? (
                  <>
                    <Avatar className="h-16 w-16">
                      <AvatarImage src={promoMini.avatar_url} alt={promoMini.username} />
                      <AvatarFallback className="font-mono text-lg">
                        {promoMini.username.slice(0, 2).toUpperCase()}
                      </AvatarFallback>
                    </Avatar>
                    <div>
                      <h2 className="text-lg font-semibold">
                        Try the demo review mini
                      </h2>
                      <p className="mt-1 text-sm text-muted-foreground">
                        See how the model explains likely blockers, delivery style,
                        and engineering priorities before a real review happens.
                      </p>
                    </div>
                    <Link href={`/m/${promoMini.username}`}>
                      <Button size="lg" className="gap-2">
                        <MessageSquare className="h-4 w-4" />
                        Open demo
                      </Button>
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      No signup required. Five free demo messages before GitHub sign-in.
                    </p>
                  </>
                ) : (
                  <>
                    <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted">
                      <Bot className="h-8 w-8 text-muted-foreground" />
                    </div>
                    <div>
                      <h2 className="text-lg font-semibold">Demo mini</h2>
                      <p className="mt-1 text-sm text-muted-foreground">
                        The demo is warming up. Try creating your own mini above,
                        or check back shortly.
                      </p>
                    </div>
                    <Link href={`/m/${PROMO_MINI}`}>
                      <Button size="lg" variant="outline" className="gap-2">
                        <MessageSquare className="h-4 w-4" />
                        Try anyway
                      </Button>
                    </Link>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        </section>
      )}

      {/* How it Works */}
      <section className="w-full border-t border-border/50 py-24">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="mb-12 text-center text-2xl font-bold tracking-tight sm:text-3xl">
            How it Works
          </h2>
          <div className="grid gap-8 sm:grid-cols-3">
            {steps.map((step) => (
              <div key={step.number} className="text-center">
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-r from-chart-1 to-chart-2 font-mono text-lg font-bold text-white">
                  {step.number}
                </div>
                <h3 className="text-base font-medium">{step.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  {step.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="w-full border-t border-border/50 py-24">
        <div className="mx-auto max-w-6xl px-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {highlights.map((item) => (
              <Card
                key={item.title}
                className="border-border/50 transition-colors hover:border-border"
              >
                <CardContent className="flex items-start gap-4 pt-6">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-secondary">
                    <item.icon className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div>
                    <h3 className="text-sm font-medium">{item.title}</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {item.description}
                    </p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* Gallery Preview */}
      {!minisLoading && readyMinis.length > 0 && (
        <section className="w-full border-t border-border/50 py-24" data-tour-target="browse-minis">
          <div className="mx-auto max-w-6xl px-4">
            <div className="mb-8 flex items-center justify-between">
              <h2 className="text-2xl font-bold tracking-tight">
                Explore live review minis
              </h2>
              <Link
                href="/gallery"
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                View all &rarr;
              </Link>
            </div>
            <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {readyMinis.map((mini) => (
                <MiniCard key={mini.id} mini={mini} />
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Final CTA */}
      <section className="w-full border-t border-border/50 py-24">
        <div className="mx-auto flex max-w-2xl flex-col items-center px-4 text-center">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
            Pre-review the change before the meeting starts
          </h2>
          <p className="mt-3 text-muted-foreground">
            Create a review mini in under a minute and keep the human reviewer as the final authority.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Button size="lg" className="gap-1.5" onClick={login}>
              Build my review mini
              <ArrowRight className="h-4 w-4" />
            </Button>
            <Button asChild size="lg" variant="outline" className="gap-1.5">
              <Link href={`/m/${PROMO_MINI}`}>
                <Sparkles className="h-4 w-4" />
                Try demo first
              </Link>
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}

function Dashboard() {
  const router = useRouter();
  const { user } = useAuth();
  const githubUsername = user?.github_username ?? null;
  const [username, setUsername] = useState("");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [avatarLoading, setAvatarLoading] = useState(false);
  const [minis, setMinis] = useState<Mini[]>([]);
  const [minisLoading, setMinisLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [myMini, setMyMini] = useState<Mini | null>(null);

  useEffect(() => {
    if (!githubUsername) return;
    import("@/lib/api").then(({ getMiniByUsername }) =>
      getMiniByUsername(githubUsername)
        .then(setMyMini)
        .catch(() => setMyMini(null))
    );
  }, [githubUsername]);

  useEffect(() => {
    if (!username.trim()) {
      setAvatarUrl(null);
      return;
    }

    setAvatarLoading(true);
    const timeout = setTimeout(() => {
      const img = new Image();
      img.onload = () => {
        setAvatarUrl(`https://github.com/${username}.png`);
        setAvatarLoading(false);
      };
      img.onerror = () => {
        setAvatarUrl(null);
        setAvatarLoading(false);
      };
      img.src = `https://github.com/${username}.png`;
    }, 400);

    return () => clearTimeout(timeout);
  }, [username]);

  useEffect(() => {
    listMinis()
      .then(setMinis)
      .catch(() => setMinis([]))
      .finally(() => setMinisLoading(false));
  }, []);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!username.trim()) return;
      setSubmitting(true);
      router.push(`/create?username=${encodeURIComponent(username.trim())}`);
    },
    [username, router]
  );

  return (
    <div className="flex flex-col items-center">
      {/* Hero */}
      <section className="flex w-full flex-col items-center px-4 pb-16 pt-24 text-center sm:pt-32">
        <h1 className="max-w-2xl text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
          Predict the{" "}
          <span className="bg-gradient-to-r from-chart-1 to-chart-2 bg-clip-text text-transparent">
            review
          </span>
          {" "}before you request it
        </h1>
        <p className="mt-4 max-w-2xl text-base text-muted-foreground sm:text-lg">
          Build a review mini from GitHub history to see what a specific
          engineer would flag, how they would deliver the feedback, and how
          closely the prediction matches the human review later.
        </p>

        <form
          onSubmit={handleSubmit}
          className="mt-10 flex w-full max-w-md flex-col items-stretch gap-3 sm:flex-row sm:items-center"
        >
          <div className="relative flex-1">
            <div className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2">
              {avatarUrl ? (
                <Avatar className="h-6 w-6">
                  <AvatarImage src={avatarUrl} alt={username} />
                  <AvatarFallback className="text-[10px]">
                    <Github className="h-3.5 w-3.5" />
                  </AvatarFallback>
                </Avatar>
              ) : avatarLoading ? (
                <Skeleton className="h-6 w-6 rounded-full" />
              ) : (
                <Github className="h-4 w-4 text-muted-foreground" />
              )}
            </div>
            <Input
              type="text"
              placeholder="GitHub username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="h-12 pl-12 font-mono text-sm"
              autoFocus
            />
          </div>
          <Button
            type="submit"
            size="lg"
            disabled={!username.trim() || submitting}
            className="h-12 gap-1.5 sm:w-auto"
          >
            Create Mini
            <ArrowRight className="h-4 w-4" />
          </Button>
        </form>
      </section>

      {/* Dashboard CTAs */}
      {githubUsername && (
        <section className="w-full max-w-6xl px-4 pb-8">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Link
              href={
                myMini
                  ? `/m/${githubUsername}`
                  : `/create?username=${githubUsername}`
              }
              className="group"
            >
              <div className="flex items-center gap-4 rounded-xl border border-chart-1/30 bg-chart-1/5 p-6 transition-all hover:border-chart-1/50">
                <Avatar className="h-12 w-12">
                  <AvatarImage
                    src={myMini?.avatar_url || undefined}
                    alt={githubUsername}
                  />
                  <AvatarFallback className="font-mono">
                    {githubUsername.slice(0, 2).toUpperCase()}
                  </AvatarFallback>
                </Avatar>
                <div>
                  <p className="font-medium">
                    {myMini ? "My Mini" : "Create My Mini"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    @{githubUsername}
                  </p>
                </div>
              </div>
            </Link>
            <Link href="/teams" className="group">
              <div className="flex items-center gap-4 rounded-xl border border-border/50 p-6 transition-all hover:border-border hover:bg-secondary/30">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary">
                  <Users className="h-5 w-5 text-muted-foreground" />
                </div>
                <div>
                  <p className="font-medium">My Teams</p>
                  <p className="text-xs text-muted-foreground">
                    Manage mini rosters
                  </p>
                </div>
              </div>
            </Link>
          </div>
        </section>
      )}

      {/* Existing Minis */}
      {(minisLoading || minis.length > 0) && (
        <section className="w-full max-w-6xl px-4 pb-16" data-tour-target="browse-minis">
          <h2 className="mb-6 text-sm font-medium uppercase tracking-wider text-muted-foreground">
            Existing Review Minis
          </h2>
          <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
            {minisLoading
              ? Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="space-y-3 rounded-xl border p-6">
                    <div className="flex items-center gap-3">
                      <Skeleton className="h-10 w-10 rounded-full" />
                      <div className="space-y-2">
                        <Skeleton className="h-4 w-24" />
                        <Skeleton className="h-3 w-16" />
                      </div>
                    </div>
                    <Skeleton className="h-8 w-full" />
                  </div>
                ))
              : minis.map((mini) => <MiniCard key={mini.id} mini={mini} />)}
          </div>
        </section>
      )}
    </div>
  );
}

export default function Home() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Skeleton className="h-8 w-48" />
      </div>
    );
  }

  return user ? <Dashboard /> : <LandingPage />;
}
