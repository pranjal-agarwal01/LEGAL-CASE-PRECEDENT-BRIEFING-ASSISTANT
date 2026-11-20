import { useEffect, useState } from "react";

import { Stamp, tiltFor } from "@/components/Stamp";
import type { Run, TraceEvent } from "@/lib/api";
import { cn } from "@/lib/utils";

const STEPS = [
  { key: "facts", label: "Reading the facts", detail: "Parties, dates, claims and the issues they raise", done: "Read" },
  { key: "research", label: "Researching", detail: "Legislation and judgments in your library", done: "Researched" },
  { key: "debate", label: "Arguing both sides", detail: "Your client's case, then the other side's answer", done: "Argued" },
  { key: "compile", label: "Writing the brief", detail: "Merging both sides with a citation for every point", done: "Drafted" },
  { key: "verify", label: "Checking sources", detail: "Each cited passage is read against the claim it supports", done: "Checked" },
];

const AGENT: Record<string, string> = {
  fact_extractor: "Facts",
  precedent_retrieval: "Research",
  argument: "Client's advocate",
  counter_argument: "Opposing counsel",
  brief_compiler: "Compiler",
  source_checker: "Source check",
  jurisdiction_check: "Jurisdiction",
  library: "Library",
  queue: "Queue",
  workflow: "Workflow",
};

function describe(e: TraceEvent): string {
  const a = e.action;
  if (a === "start" && e.agent === "library") return "Loading your library";
  if (a === "queued") return "Waiting for a free worker";
  if (a.startsWith("turn_")) return `Round ${a.slice(5)}: ${e.detail}`;
  if (a === "llm_fallback") return "Model step failed; used the basic method for this step";
  if (a === "attached") return `Found authorities for ${e.detail.split(":")[0]}`;
  if (a === "citation_guard") return "Removed citations that do not exist";
  return e.detail || a.replace(/_/g, " ");
}

export function RunProgress({ run }: { run: Run }) {
  const events = run.events ?? [];
  const stage = [...events].reverse().find((e) => e.stage && e.stage !== "queued")?.stage ?? "queued";
  const current = STEPS.findIndex((s) => s.key === stage);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const elapsed = Math.max(0, Math.round((now - new Date(run.created_at).getTime()) / 1000));
  const recent = events.filter((e) => e.agent !== "workflow").slice(-7);

  return (
    <section aria-live="polite" className="desk px-3 py-8 sm:px-6 lg:py-10">
      <div className="mx-auto grid max-w-[66rem] gap-6 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)] lg:items-start">
        <div className="sheet">
          <h2 className="font-serif text-2xl font-semibold text-ink">Preparing the brief</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            <span className="tabular-nums">{Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}</span> elapsed.
            Most briefs take two to three minutes. You can leave this page; the brief keeps going.
          </p>
          <ol className="mt-5 border-t border-dashed">
            {STEPS.map((s, i) => {
              const state = i < current ? "done" : i === current ? "active" : "todo";
              return (
                <li key={s.key} className="slip-row">
                  <span className="min-w-0">
                    <span className={cn("block font-semibold", state === "todo" ? "text-muted-foreground" : "text-ink")}>
                      {s.label}
                      {state === "active" ? <span className="sr-only"> (in progress)</span> : null}
                      {state === "done" ? <span className="sr-only"> (done)</span> : null}
                    </span>
                    <span className="block text-[13px] text-muted-foreground">{s.detail}</span>
                  </span>
                  <span className="slip-slot" aria-hidden="true">
                    {state === "done" ? (
                      <Stamp tone="seal" thud tilt={tiltFor(s.key, 6)} className="text-[13px]">{s.done}</Stamp>
                    ) : state === "active" ? (
                      <span className="pulse text-[12px] font-semibold text-seal">In progress</span>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
        <div className="min-w-0 rounded-sm border border-manila-deep bg-vellum p-4 sm:p-5">
          <h3 className="text-sm font-semibold text-ink-soft">Working notes</h3>
          <ul className="mt-3 grid gap-2.5 text-sm">
            {recent.map((e, i) => (
              <li key={`${e.t}-${i}`} className="grid grid-cols-[minmax(0,8.5rem)_minmax(0,1fr)] gap-3">
                <span className="truncate font-semibold text-ink-soft">{AGENT[e.agent] ?? e.agent}</span>
                <span className={cn("min-w-0 break-words", i === recent.length - 1 ? "text-ink" : "text-muted-foreground")}>
                  {describe(e)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
