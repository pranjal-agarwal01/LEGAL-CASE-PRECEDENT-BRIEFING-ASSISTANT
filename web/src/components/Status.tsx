import type { RunSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

export function StatusText({ run }: { run: RunSummary }) {
  if (run.status === "queued" || run.status === "running") {
    return (
      <span className="inline-flex items-center gap-2 text-ink">
        <span className="pulse size-2 rounded-full bg-tape" aria-hidden="true" /> Preparing
      </span>
    );
  }
  if (run.status === "failed") return <span className="text-unsupported">Failed</span>;
  return (
    <span className="text-ink-soft">
      {run.issues ?? 0} {run.issues === 1 ? "issue" : "issues"}
      {run.unsupported ? (
        <span className="ml-2 text-unsupported">{run.unsupported} unsupported</span>
      ) : null}
    </span>
  );
}

export function SupportMark({ support, className }: { support: string; className?: string }) {
  const map: Record<string, { sym: string; label: string }> = {
    supported: { sym: "✓", label: "Verified against the cited source" },
    partial: { sym: "~", label: "Partly supported: the statement goes beyond the cited source" },
    unsupported: { sym: "!", label: "Not supported by the cited source" },
    facts_only: { sym: "F", label: "Rests on the facts only" },
    unchecked: { sym: "·", label: "Not checked against a source" },
  };
  const m = map[support] ?? map.unchecked;
  return (
    <span className={cn("mark", `mark-${support}`, className)} role="img" aria-label={m.label} title={m.label}>
      {m.sym}
    </span>
  );
}
