"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Check } from "lucide-react";

const tiers = [
  {
    name: "Free",
    price: "$0",
    period: "/month",
    description: "Start with public GitHub review evidence",
    features: [
      "5 review minis",
      "Public GitHub commits, PRs, and reviews",
      "Manual pre-review in chat",
      "Agreement scorecard preview",
    ],
    cta: "Get Started",
    href: "/",
    highlighted: false,
    comingSoon: false,
  },
  {
    name: "Team",
    price: "$19",
    period: "/month",
    description: "For teams running predictive review loops",
    features: [
      "25 review minis",
      "Shared reviewer roster",
      "Private repo analysis",
      "GitHub and terminal workflows",
      "Agreement metrics dashboard",
    ],
    cta: "Coming Soon",
    href: "#",
    highlighted: true,
    comingSoon: true,
  },
  {
    name: "Enterprise",
    price: "Custom",
    period: "",
    description: "For org-wide review intelligence",
    features: [
      "Unlimited review minis",
      "SSO / SAML",
      "Self-hosted option",
      "Dedicated support",
      "Custom evaluation and workflow integrations",
    ],
    cta: "Contact Us",
    href: "/",
    highlighted: false,
    comingSoon: false,
  },
];

const faqs = [
  {
    question: "How accurate are the review predictions?",
    answer:
      "Accuracy depends on the amount and quality of review evidence. Commits help, but PR history and review comments matter most because they reveal what the engineer actually notices and blocks on.",
  },
  {
    question: "Does Minis replace the human reviewer?",
    answer:
      "No. Minis is for pre-review workflows and asynchronous preparation. The human reviewer keeps final judgment, and disagreement between the mini and the human becomes part of the learning loop.",
  },
  {
    question: "What do the agreement metrics measure?",
    answer:
      "We focus on approval accuracy, blocker precision, and comment overlap. The point is not whether the output sounds plausible. The point is whether it matches the review the engineer actually gives later.",
  },
];

export default function PricingPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-20">
      <div className="mb-16 text-center">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Pricing
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
          Start with public review evidence, then scale into team workflows and agreement tracking.
        </p>
      </div>

      <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-3">
        {tiers.map((tier) => (
          <Card
            key={tier.name}
            className={
              tier.highlighted
                ? "relative border-chart-1/50 shadow-lg shadow-chart-1/5"
                : "border-border/50"
            }
          >
            {tier.highlighted && (
              <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                <Badge className="bg-chart-1 text-white">Popular</Badge>
              </div>
            )}
            <CardHeader>
              <CardTitle className="text-lg">
                {tier.name}
                {tier.comingSoon && (
                  <span className="ml-2 inline-block rounded-full bg-chart-1/20 px-2 py-0.5 text-[10px] font-medium text-chart-1">
                    Coming Soon
                  </span>
                )}
              </CardTitle>
              <CardDescription>{tier.description}</CardDescription>
              <div className="pt-2">
                <span className="text-3xl font-bold">{tier.price}</span>
                {tier.period && (
                  <span className="text-sm text-muted-foreground">
                    {tier.period}
                  </span>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <ul className="space-y-3">
                {tier.features.map((feature) => (
                  <li key={feature} className="flex items-center gap-2 text-sm">
                    <Check className="h-4 w-4 shrink-0 text-chart-2" />
                    <span className="text-muted-foreground">{feature}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
            <CardFooter>
              <Button
                asChild
                variant={tier.highlighted ? "default" : "outline"}
                className="w-full"
                disabled={tier.comingSoon}
              >
                <Link href={tier.href}>{tier.cta}</Link>
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>

      <div className="mx-auto mt-24 max-w-2xl">
        <h2 className="mb-8 text-center text-2xl font-bold tracking-tight">
          Frequently Asked Questions
        </h2>
        <div className="space-y-6">
          {faqs.map((faq) => (
            <div key={faq.question}>
              <h3 className="font-medium">{faq.question}</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                {faq.answer}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
