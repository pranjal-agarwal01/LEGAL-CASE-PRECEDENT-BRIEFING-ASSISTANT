import type { CSSProperties, ReactNode } from "react";

import type { Reliability } from "@/lib/api";
import { cn } from "@/lib/utils";

export type StampTone = "verified" | "partial" | "unsupported" | "seal" | "quiet";

/** A steady, slightly different angle for each stamp, so a page of them looks hand-pressed. */
export function tiltFor(seed: string, range = 4): number {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  return ((Math.abs(h) % (range * 20 + 1)) / 10) - range;
}

/** A rubber stamp in one ink. `thud` presses it onto the page when it first appears. */
export function Stamp({
  tone, children, small, thud, tilt = -5, delay = 0, className, style,
}: {
  tone: StampTone;
  children: ReactNode;
  small?: boolean;
  thud?: boolean;
  tilt?: number;
  delay?: number;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <span
      className={cn("stamp ink-grain", `stamp-${tone}`, small && "stamp-sm", thud && "stamp-thud", className)}
      style={{ "--tilt": `${tilt}deg`, "--delay": `${delay}ms`, ...style } as CSSProperties}
    >
      {children}
    </span>
  );
}

export const RELIABILITY_STAMP: Record<Reliability, { short: string; long: string; tone: StampTone }> = {
  high: { short: "Solid", long: "Solid starting point", tone: "verified" },
  medium: { short: "Use with care", long: "Use with care", tone: "partial" },
  low: { short: "Not reliable", long: "Not reliable as it stands", tone: "unsupported" },
  unchecked: { short: "Unchecked", long: "Sources not checked", tone: "quiet" },
};
