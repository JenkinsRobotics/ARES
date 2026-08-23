/**
 * WHAT: Dynamic overflow detection hook using ResizeObserver.
 * WHERE YOU SEE IT: Composer toolbar wrapper in ConversationPage.tsx.
 * MEASURES: Compares scrollWidth vs clientWidth to detect overflow.
 * RETURNS: Overflow stage (0=full, 1=icons-only, 2=burger-overflow).
 * DENSITY: Respects user preference (auto/always-full/compact).
 */

import { useState, useEffect, useCallback, useRef } from "react";

export type OverflowStage = 0 | 1 | 2; // 0=full labels, 1=icons-only, 2=burger
export type DensityPreference = "auto" | "always-full" | "compact";

export interface UseDynamicOverflowResult {
  stage: OverflowStage;
  containerRef: React.RefObject<HTMLDivElement>;
  setDensity: (density: DensityPreference) => void;
  density: DensityPreference;
}

const STAGE_1_THRESHOLD = 0.85; // Show icons-only when 85% filled
const STAGE_2_THRESHOLD = 0.95; // Show burger when 95% filled

export function useDynamicOverflow(
  initialDensity: DensityPreference = "auto"
): UseDynamicOverflowResult {
  const [stage, setStage] = useState<OverflowStage>(0);
  const [density, setDensityState] = useState<DensityPreference>(initialDensity);
  const containerRef = useRef<HTMLDivElement>(null);

  const calculateStage = useCallback((element: HTMLDivElement): OverflowStage => {
    if (density === "always-full") return 0;
    if (density === "compact") return 2;
    
    const { scrollWidth, clientWidth } = element;
    const ratio = scrollWidth / clientWidth;

    if (ratio < STAGE_1_THRESHOLD) return 0;
    if (ratio < STAGE_2_THRESHOLD) return 1;
    return 2;
  }, [density]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const observer = new ResizeObserver(() => {
      const newStage = calculateStage(element);
      setStage((prev) => (prev !== newStage ? newStage : prev));
    });

    observer.observe(element);
    // Initial calculation
    setStage(calculateStage(element));

    return () => observer.disconnect();
  }, [calculateStage]);

  const setDensity = useCallback((newDensity: DensityPreference) => {
    setDensityState(newDensity);
    setStage(0); // Reset stage to trigger recalculation
  }, []);

  // Type assertion to satisfy interface - containerRef is always HTMLDivElement | null
  return { 
    stage, 
    containerRef: containerRef as unknown as React.RefObject<HTMLDivElement>,
    setDensity, 
    density 
  };
}
