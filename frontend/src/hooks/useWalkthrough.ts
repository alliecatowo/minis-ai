"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getSettings, markWalkthroughSeen } from "@/lib/api";

interface UseWalkthroughOptions {
  enabled: boolean;
}

export interface UseWalkthroughResult {
  isActive: boolean;
  runId: number;
  replayTour: () => void;
  finishTour: () => Promise<void>;
}

export function useWalkthrough({ enabled }: UseWalkthroughOptions): UseWalkthroughResult {
  const [isActive, setIsActive] = useState(false);
  const [runId, setRunId] = useState(0);
  const initializedRef = useRef(false);
  const markedSeenRef = useRef(false);

  const replayTour = useCallback(() => {
    setRunId((prev) => prev + 1);
    setIsActive(true);
  }, []);

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

  useEffect(() => {
    if (!enabled) {
      setIsActive(false);
      initializedRef.current = false;
      markedSeenRef.current = false;
      return;
    }
    if (initializedRef.current) return;
    initializedRef.current = true;

    let cancelled = false;
    void getSettings()
      .then((settings) => {
        if (cancelled) return;
        if (settings.walkthrough_seen_v1) {
          markedSeenRef.current = true;
          return;
        }
        replayTour();
      })
      .catch(() => {
        // If settings fails, leave walkthrough inactive.
      });

    return () => {
      cancelled = true;
    };
  }, [enabled, replayTour]);

  return {
    isActive,
    runId,
    replayTour,
    finishTour,
  };
}
