"use client";

import { useState } from "react";
import { Github } from "lucide-react";

import { TosDialog } from "@/components/tos-dialog";
import { Button } from "@/components/ui/button";
import { TOS_VERSION } from "@/lib/constants";
import { useAuth } from "@/lib/auth";

export default function SignupPage() {
  const { login } = useAuth();
  const [tosOpen, setTosOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleAgree = async () => {
    setSubmitting(true);
    setTosOpen(false);
    login();
  };

  return (
    <div className="mx-auto flex min-h-[calc(100vh-8rem)] w-full max-w-3xl items-center px-6 py-16">
      <section className="w-full space-y-8">
        <div className="space-y-4">
          <p className="text-sm uppercase tracking-[0.2em] text-muted-foreground">
            Signup
          </p>
          <h1 className="text-4xl font-semibold tracking-tight sm:text-6xl">
            Build your mini and predict reviews before they arrive.
          </h1>
          <p className="max-w-2xl text-base text-muted-foreground sm:text-lg">
            Connect GitHub once, generate your decision framework clone, and
            validate alignment against real review outcomes.
          </p>
        </div>

        <ul className="space-y-3 text-base text-foreground">
          <li>Fast onboarding from your public engineering history.</li>
          <li>Pre-review signals that mirror your framework and style.</li>
          <li>Evidence-backed outputs you can iterate and calibrate.</li>
        </ul>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Button
            size="lg"
            className="gap-2"
            onClick={() => setTosOpen(true)}
            disabled={submitting}
          >
            <Github className="h-4 w-4" />
            Continue with GitHub
          </Button>
          <p className="text-xs text-muted-foreground">
            Terms version {TOS_VERSION}
          </p>
        </div>
      </section>

      <TosDialog
        open={tosOpen}
        onOpenChange={setTosOpen}
        title="Terms of Service"
        description="Review and accept the Terms of Service before continuing with GitHub."
        onAgree={handleAgree}
        onCancel={() => setTosOpen(false)}
      />
    </div>
  );
}
