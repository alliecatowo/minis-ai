"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";

type WalkthroughStep = {
  id: string;
  title: string;
  content: string;
  targetSelector: string;
};

const WALKTHROUGH_STEPS: WalkthroughStep[] = [
  {
    id: "welcome",
    title: "Welcome",
    content:
      "Welcome to Minis. A mini is your AI personality clone — trained on your GitHub and the tools you use.",
    targetSelector: "[data-tour-target='brand']",
  },
  {
    id: "create-mini",
    title: "Create your mini",
    content: "Start by creating one for yourself.",
    targetSelector: "[data-tour-target='create-mini']",
  },
  {
    id: "browse-minis",
    title: "Browse while it builds",
    content:
      "While we generate your soul doc, you can browse other minis on the home page.",
    targetSelector: "[data-tour-target='browse-minis']",
  },
  {
    id: "mini-card",
    title: "Open any mini",
    content: "Click any mini to chat with them.",
    targetSelector: "[data-tour-target='mini-card']",
  },
  {
    id: "chat-input",
    title: "Start chatting",
    content:
      "Ask anything — code review, opinions, frameworks, debugging.",
    targetSelector: "[data-tour-target='chat-input']",
  },
  {
    id: "settings",
    title: "Settings",
    content:
      "Configure your provider keys, manage your minis, and view your data here.",
    targetSelector: "[data-tour-target='settings-nav']",
  },
  {
    id: "replay",
    title: "Replay anytime",
    content:
      "That's it. You can replay this tour anytime from the help menu.",
    targetSelector: "[data-tour-target='replay-tour']",
  },
];

interface WalkthroughProps {
  isActive: boolean;
  runId: number;
  onComplete: () => void | Promise<void>;
}

interface AnchorPosition {
  top: number;
  left: number;
}

export function Walkthrough({ isActive, runId, onComplete }: WalkthroughProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [isOpen, setIsOpen] = useState(false);
  const [anchorPosition, setAnchorPosition] = useState<AnchorPosition>({
    top: 120,
    left: 200,
  });

  const step = WALKTHROUGH_STEPS[currentStep];
  const isFinalStep = currentStep === WALKTHROUGH_STEPS.length - 1;

  useEffect(() => {
    if (!isActive) {
      setIsOpen(false);
      return;
    }
    setCurrentStep(0);
    setIsOpen(true);
  }, [isActive, runId]);

  useEffect(() => {
    if (!isOpen) return;

    const resolveTarget = () =>
      document.querySelector(step.targetSelector) as HTMLElement | null;

    const updateAnchor = () => {
      const target = resolveTarget();
      if (!target) {
        setAnchorPosition({
          top: Math.max(window.innerHeight * 0.25, 120),
          left: window.innerWidth / 2,
        });
        return;
      }
      const rect = target.getBoundingClientRect();
      setAnchorPosition({
        top: Math.min(rect.bottom + 10, window.innerHeight - 20),
        left: Math.min(Math.max(rect.left + rect.width / 2, 24), window.innerWidth - 24),
      });
    };

    const highlightTarget = () => {
      const target = resolveTarget();
      if (!target) return () => {};
      target.classList.add("walkthrough-highlight-target");
      return () => target.classList.remove("walkthrough-highlight-target");
    };

    updateAnchor();
    const cleanupHighlight = highlightTarget();

    window.addEventListener("resize", updateAnchor);
    window.addEventListener("scroll", updateAnchor, true);
    return () => {
      cleanupHighlight();
      window.removeEventListener("resize", updateAnchor);
      window.removeEventListener("scroll", updateAnchor, true);
    };
  }, [isOpen, step.targetSelector]);

  const handleSkip = async () => {
    setIsOpen(false);
    await onComplete();
  };

  const handleNext = async () => {
    if (isFinalStep) {
      setIsOpen(false);
      await onComplete();
      return;
    }
    setCurrentStep((prev) => prev + 1);
  };

  const progress = useMemo(
    () => `${currentStep + 1} / ${WALKTHROUGH_STEPS.length}`,
    [currentStep],
  );

  return (
    <Popover open={isOpen}>
      <PopoverAnchor asChild>
        <span
          aria-hidden
          className="pointer-events-none fixed z-[99] h-px w-px"
          style={{ top: anchorPosition.top, left: anchorPosition.left }}
        />
      </PopoverAnchor>
      <PopoverContent
        side="bottom"
        align="center"
        sideOffset={12}
        className="z-[100] w-[min(92vw,380px)] border-border/70 bg-background/98 backdrop-blur"
      >
        <div className="space-y-4">
          <div className="space-y-1">
            <p className="text-[11px] font-mono uppercase tracking-[0.18em] text-muted-foreground">
              Walkthrough {progress}
            </p>
            <h3 className="text-sm font-semibold">{step.title}</h3>
            <p className="text-sm text-muted-foreground">{step.content}</p>
          </div>
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={handleSkip}>
              Skip
            </Button>
            <Button size="sm" onClick={handleNext}>
              {isFinalStep ? "Finish" : "Next"}
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
