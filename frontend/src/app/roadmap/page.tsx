import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  BarChart3,
  Rocket,
  Users,
  Zap,
  Bot,
  Sparkles,
  GitBranch,
  Globe,
} from "lucide-react";

const roadmap = [
  {
    phase: "Now",
    icon: Rocket,
    items: [
      {
        title: "GitHub review evidence",
        description: "Commits, pull requests, reviews, and repo context as the core prediction signal",
        status: "live",
      },
      {
        title: "Repo and source controls",
        description: "Choose which repos and evidence sources define a review mini",
        status: "live",
      },
      {
        title: "Pre-review in Claude Code",
        description: "Bring reviewer context into terminal workflows before the PR request goes out",
        status: "live",
      },
      {
        title: "Shared review minis",
        description: "Use the same reviewer models across chat, gallery, and team surfaces",
        status: "live",
      },
    ],
  },
  {
    phase: "Next",
    icon: Zap,
    items: [
      {
        title: "Slack integration",
        description: "Ask for predicted review feedback in the team channels where discussion already happens",
        status: "in-progress",
      },
      {
        title: "GitHub PR reviews",
        description: "Install the GitHub App and post predictive review output directly on pull requests",
        status: "in-progress",
      },
      {
        title: "Private repo analysis",
        description: "Add private code and review history so the model reflects the real engineering environment",
        status: "planned",
      },
    ],
  },
  {
    phase: "Soon",
    icon: Globe,
    items: [
      {
        title: "Agreement scorecards",
        description: "Track approval accuracy, blocker precision, and comment overlap for every review mini",
        status: "planned",
      },
      {
        title: "Reviewer-aware author adaptation",
        description: "Model how the same reviewer changes delivery for juniors, peers, and cross-team partners",
        status: "planned",
      },
      {
        title: "Learning from review deltas",
        description: "Capture where the human review disagreed and feed that signal back into the next synthesis",
        status: "planned",
      },
    ],
  },
  {
    phase: "Future",
    icon: Sparkles,
    items: [
      {
        title: "Review-guided code rewriting",
        description: "Use the predicted review to revise code before a human reviewer spends time on it",
        status: "envisioned",
      },
      {
        title: "Cross-team review policy maps",
        description: "Make the differing standards across teams explicit before big architectural work begins",
        status: "envisioned",
      },
      {
        title: "Reviewer-native code generation",
        description: "Generate code under a specific engineer's framework only after the review prediction loop is trustworthy",
        status: "envisioned",
      },
    ],
  },
];

const vision = [
  {
    icon: Users,
    title: "Pre-Review Before You Ask",
    description:
      "Minis should let a developer see the likely review before they page the reviewer, reducing predictable back-and-forth and protecting human attention.",
  },
  {
    icon: BarChart3,
    title: "Measure Agreement",
    description:
      "The model should be evaluated against the real human review with concrete metrics, not judged on whether it sounds convincing.",
  },
  {
    icon: Bot,
    title: "Preserve Engineering Judgment",
    description:
      "The point is to preserve what the engineer notices, ignores, and chooses to say in context, not to build a general-purpose personality clone.",
  },
  {
    icon: GitBranch,
    title: "Expand from Review to Code",
    description:
      "Once review prediction is reliable, the same framework can help rewrite code to satisfy the reviewer before a human ever reads the diff.",
  },
];

export default function RoadmapPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-20">
      <div className="mb-16 text-center">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Roadmap
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
          Review prediction first. Agreement metrics, workflow surfaces, and code assistance follow from there.
        </p>
      </div>

      {/* Vision */}
      <section className="mb-20">
        <h2 className="mb-8 text-center text-2xl font-bold tracking-tight">
          The Vision
        </h2>
        <div className="grid gap-6 sm:grid-cols-2">
          {vision.map((item) => (
            <Card key={item.title} className="border-border/50">
              <CardHeader className="flex-row items-center gap-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-r from-chart-1 to-chart-2">
                  <item.icon className="h-5 w-5 text-white" />
                </div>
                <CardTitle className="text-base">{item.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  {item.description}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Roadmap */}
      <section>
        {roadmap.map((phase) => (
          <div key={phase.phase} className="mb-12">
            <div className="mb-6 flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary">
                <phase.icon className="h-4 w-4 text-muted-foreground" />
              </div>
              <h3 className="text-xl font-bold">{phase.phase}</h3>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {phase.items.map((item) => (
                <Card key={item.title} className="border-border/50">
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-sm">{item.title}</CardTitle>
                      <Badge
                        variant="outline"
                        className={
                          item.status === "live"
                            ? "border-chart-2 text-chart-2"
                            : item.status === "in-progress"
                              ? "border-chart-1 text-chart-1"
                              : "border-muted-foreground/50 text-muted-foreground"
                        }
                      >
                        {item.status === "live"
                          ? "Live"
                          : item.status === "in-progress"
                            ? "In Progress"
                            : item.status === "planned"
                              ? "Planned"
                              : "Envisioned"}
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-xs text-muted-foreground">
                      {item.description}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
