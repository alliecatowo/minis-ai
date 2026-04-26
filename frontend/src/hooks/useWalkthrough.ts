"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { markWalkthroughSeen } from "@/lib/api";

interface UseWalkthroughOptions {
  enabled: boolean;
}

export interface UseWalkthroughResult {
  isActive: boolean;
  runId: number;
  replayTour: () => void;
  finishTour: () => Promise<void>;
  dismissTour: () => void;
}

export function useWalkthrough({ enabled }: UseWalkthroughOptions): UseWalkthroughResult {
  const [isActive, setIsActive] = useState(false);
  const [runId, setRunId] = useState(0);
  const markedSeenRef = useRef(false);

  const replayTour = useCallback(() => {
    if (!enabled) return;
    setRunId((prev) => prev + 1);
    setIsActive(true);
  }, [enabled]);

  const finishTour = useCallback(async () => {
    setIsActive(false);
    if (markedSeenRef.current) return;
    markedSeenRef.current = true;
    try {
      await markWalkthroughSeen();
    } catch {
      markedSeenRef.current = false;
    }
  }, []);

  const dismissTour = useCallback(() => {
    setIsActive(false);
  }, []);

  useEffect(() => {
    if (!enabled) {
      setIsActive(false);
      markedSeenRef.current = false;
    }
  }, [enabled]);

  return {
    isActive,
    runId,
    replayTour,
    finishTour,
    dismissTour,
  };
}
