import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  BarChart3,
  FolderGit2,
  GitBranch,
  MessageSquare,
  ShieldCheck,
  Wrench,
  Zap,
  RefreshCw,
} from "lucide-react";

const features = [
  {
    icon: Zap,
    title: "Review Prediction on Novel Work",
    description:
      "Predict what a specific engineer will block on, question, or approve before the PR request goes out.",
  },
  {
    icon: MessageSquare,
    title: "Pre-Review Workflows",
    description:
      "Ask what this reviewer would say, rewrite the diff before review, and use the mini as a daily prep surface instead of a novelty chat bot.",
  },
  {
    icon: BarChart3,
    title: "Agreement Scorecard",
    description:
      "Measure approval accuracy, blocker precision, and comment overlap against the eventual human review.",
  },
  {
    icon: ShieldCheck,
    title: "Preserved Engineering Judgment",
    description:
      "Model both the private assessment and the expressed feedback so the system learns judgment, not just tone.",
  },
  {
    icon: FolderGit2,
    title: "Repo-Aware Context",
    description:
      "Ground predictions in repo conventions, review history, and the exact code surface that shaped the reviewer over time.",
  },
  {
    icon: GitBranch,
    title: "Scoped Evidence Controls",
    description:
      "Choose which repos and sources count so the model reflects the engineer's actual review context instead of broad internet exhaust.",
  },
  {
    icon: Wrench,
    title: "Claude Code Integration",
    description:
      "Bring reviewer context into terminal workflows so engineers can pre-flight changes before asking for human attention.",
  },
  {
    icon: RefreshCw,
    title: "Closed-Loop Learning",
    description:
      "When the human review disagrees, that delta becomes evidence for the next synthesis instead of being discarded.",
  },
];

const whyMinis = [
  {
    title: "Private Assessment",
    description:
      "The mini predicts what the reviewer actually thinks after reading the change: bugs, architecture issues, rollout risk, tests, and the things they choose not to say out loud.",
  },
  {
    title: "Delivery Policy",
    description:
      "Review output changes with the author, urgency, and team norms. Minis models that policy so it does not over-review every diff the same way.",
  },
  {
    title: "Expressed Feedback",
    description:
      "The product surface is the feedback the reviewer would actually leave in public, with the right severity, tone, and selectivity for the situation.",
  },
];

export default function FeaturesPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-20">
      <div className="mb-16 text-center">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Features
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
          Minis is built to predict how a specific engineer reviews a change,
          then make that prediction usable before the human review starts.
        </p>
      </div>

      {/* Review Model */}
      <section className="mb-16">
        <div className="mx-auto max-w-3xl">
          <div className="grid gap-6">
            {whyMinis.map((item) => (
              <Card key={item.title} className="border-border/50">
                <CardHeader>
                  <CardTitle className="text-lg">{item.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-muted-foreground">
                    {item.description}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <div className="grid gap-6 sm:grid-cols-2">
        {features.map((feature) => (
          <Card
            key={feature.title}
            className="border-border/50 transition-colors hover:border-border"
          >
            <CardHeader className="flex-row items-center gap-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-secondary">
                <feature.icon className="h-5 w-5 text-muted-foreground" />
              </div>
              <CardTitle className="text-base">{feature.title}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                {feature.description}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
