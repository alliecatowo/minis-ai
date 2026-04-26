"use client";

import { createContext, useContext, type ReactNode } from "react";
import { Walkthrough } from "@/components/onboarding/Walkthrough";
import { useWalkthrough } from "@/hooks/useWalkthrough";
import { useAuth } from "@/lib/auth";

type WalkthroughControls = {
  replayTour: () => void;
};

const WalkthroughContext = createContext<WalkthroughControls>({
  replayTour: () => {},
});

export function WalkthroughProvider({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const walkthrough = useWalkthrough({
    enabled: !loading && !!user,
  });

  return (
    <WalkthroughContext.Provider value={{ replayTour: walkthrough.replayTour }}>
      {children}
      <Walkthrough
        isActive={walkthrough.isActive}
        runId={walkthrough.runId}
        onComplete={walkthrough.finishTour}
      />
    </WalkthroughContext.Provider>
  );
}

export function useWalkthroughControls() {
  return useContext(WalkthroughContext);
}
