"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { Walkthrough } from "@/components/onboarding/Walkthrough";
import { Button } from "@/components/ui/button";
import { useWalkthrough } from "@/hooks/useWalkthrough";
import { useAuth } from "@/lib/auth";
import { getSettings, markWalkthroughSeen } from "@/lib/api";
import { TOS_VERSION } from "@/lib/constants";

type WalkthroughControls = {
  replayTour: () => void;
};

const WalkthroughContext = createContext<WalkthroughControls>({
  replayTour: () => {},
});

const SESSION_DISMISSED_KEY = "walkthrough_bubble_dismissed_v1";

interface MeResponse {
  tos_version_accepted: string | null;
}

export function WalkthroughProvider({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const walkthrough = useWalkthrough({
    enabled: !loading && !!user,
  });
  const [tosAccepted, setTosAccepted] = useState(false);
  const [tosChecked, setTosChecked] = useState(false);
  const [walkthroughSeen, setWalkthroughSeen] = useState(false);
  const [bubbleVisible, setBubbleVisible] = useState(false);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      setTosAccepted(false);
      setTosChecked(false);
      setWalkthroughSeen(false);
      setBubbleVisible(false);
      return;
    }

    let active = true;
    setTosChecked(false);
    void fetch("/api/proxy/auth/me", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) return { tos_version_accepted: null } as MeResponse;
        return (await response.json()) as MeResponse;
      })
      .then((data) => {
        if (!active) return;
        setTosAccepted(data.tos_version_accepted === TOS_VERSION);
      })
      .catch(() => {
        if (!active) return;
        setTosAccepted(false);
      })
      .finally(() => {
        if (active) setTosChecked(true);
      });

    return () => {
      active = false;
    };
  }, [loading, user]);

  useEffect(() => {
    if (loading || !user || !tosChecked || !tosAccepted) {
      setBubbleVisible(false);
      return;
    }

    let active = true;
    void getSettings()
      .then((settings) => {
        if (!active) return;
        if (settings.walkthrough_seen_v1) {
          setWalkthroughSeen(true);
          setBubbleVisible(false);
          return;
        }

        setWalkthroughSeen(false);
        const dismissedThisSession =
          typeof window !== "undefined" &&
          window.sessionStorage.getItem(SESSION_DISMISSED_KEY) === "1";
        setBubbleVisible(!dismissedThisSession);
      })
      .catch(() => {
        if (!active) return;
        setBubbleVisible(false);
      });

    return () => {
      active = false;
    };
  }, [loading, user, tosAccepted, tosChecked]);

  const showBubble = useMemo(
    () =>
      !loading &&
      !!user &&
      tosChecked &&
      tosAccepted &&
      !walkthroughSeen &&
      bubbleVisible &&
      !walkthrough.isActive,
    [bubbleVisible, loading, tosAccepted, tosChecked, user, walkthrough.isActive, walkthroughSeen],
  );

  const dismissForSession = () => {
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(SESSION_DISMISSED_KEY, "1");
    }
    setBubbleVisible(false);
  };

  const handleTakeTour = () => {
    setBubbleVisible(false);
    walkthrough.replayTour();
  };

  const handleMaybeLater = async () => {
    setBubbleVisible(false);
    try {
      await markWalkthroughSeen();
      setWalkthroughSeen(true);
    } catch {
      setBubbleVisible(true);
    }
  };

  const handleTourComplete = async () => {
    await walkthrough.finishTour();
    setWalkthroughSeen(true);
    setBubbleVisible(false);
  };

  const handleTourDismiss = () => {
    walkthrough.dismissTour();
    dismissForSession();
  };

  return (
    <WalkthroughContext.Provider value={{ replayTour: walkthrough.replayTour }}>
      {children}
      {showBubble && (
        <div className="fixed bottom-5 right-5 z-[90] w-[min(92vw,360px)] rounded-xl border border-border/70 bg-background/95 p-4 shadow-2xl backdrop-blur">
          <button
            type="button"
            aria-label="Dismiss walkthrough prompt"
            className="absolute right-2 top-2 rounded p-1 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
            onClick={dismissForSession}
          >
            <X className="h-3.5 w-3.5" />
          </button>
          <p className="pr-6 text-sm font-medium">Welcome to Minis 👋 Take a quick tour?</p>
          <div className="mt-3 flex items-center gap-2">
            <Button size="sm" onClick={handleTakeTour}>
              Take tour
            </Button>
            <Button size="sm" variant="ghost" onClick={handleMaybeLater}>
              Maybe later
            </Button>
          </div>
        </div>
      )}
      <Walkthrough
        isActive={walkthrough.isActive}
        runId={walkthrough.runId}
        onComplete={handleTourComplete}
        onDismiss={handleTourDismiss}
      />
    </WalkthroughContext.Provider>
  );
}

export function useWalkthroughControls() {
  return useContext(WalkthroughContext);
}
