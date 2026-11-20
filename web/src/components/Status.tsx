import type { CSSProperties } from "react";

import { RELIABILITY_STAMP, Stamp, tiltFor } from "@/components/Stamp";
import type { RunSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

export function StatusText({ run }: { run: RunSummary }) {
  if (run.status === "queued" || run.status === "running") {
    return (
      <span className="inline-flex items-center gap-2 text-ink">
        <span className="pulse size-2 rounded-full bg-seal" aria-hidden="true" /> Preparing
      </span>
    );
  }
  if (run.status === "failed") return <span className="text-unsupported">Failed</span>;
  if (run.status === "blocked") return <Stamp tone="unsupported" small tilt={-3}>Stopped</Stamp>;
  const r = RELIABILITY_STAMP[run.reliability ?? "unchecked"] ?? RELIABILITY_STAMP.unchecked;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
      <Stamp tone={r.tone} small tilt={tiltFor(String(run.id), 3)}>{r.short}</Stamp>
      <span className="text-[13px] text-ink-soft">
        {run.issues ?? 0} {run.issues === 1 ? "issue" : "issues"}
      </span>
    </span>
  );
}

const MARKS: Record<string, { sym: string; label: string }> = {
  supported: { sym: "✓", label: "Verified against the cited source" },
  partial: { sym: "~", label: "Partly supported: the statement goes beyond the cited source" },
  unsupported: { sym: "!", label: "Not supported by the cited source" },
  facts_only: { sym: "F", label: "Rests on the facts only" },
  unchecked: { sym: "·", label: "Not checked against a source" },
};

/** The small square stamp in the margin beside each statement. */
export function SupportMark({ support, className, seed = "" }: { support: string; className?: string; seed?: string }) {
  const m = MARKS[support] ?? MARKS.unchecked;
  return (
    <span className={cn("mark ink-grain", `mark-${support}`, className)} role="img" aria-label={m.label} title={m.label}
      style={{ "--tilt": `${seed ? tiltFor(seed, 5) : 0}deg` } as CSSProperties}>
      {m.sym}
    </span>
  );
}
