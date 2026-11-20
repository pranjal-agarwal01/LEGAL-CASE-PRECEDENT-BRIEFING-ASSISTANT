import { Check, Copy, ExternalLink } from "lucide-react";
import { createContext, memo, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { SupportMark } from "@/components/Status";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  KIND_LABEL, type AuthorityRef, type IssueAnalysis, type PrecedentEntry, type RunResult, type Statement,
} from "@/lib/api";
import { cn } from "@/lib/utils";

// ------------------------------------------------------------------ shared context
type CiteCtx = {
  auths: Record<string, AuthorityRef>;
  facts: Map<string, string>;
  open: (cite: string) => void;
  active: string | null;
  ids: Map<Statement, string>;
};
const Ctx = createContext<CiteCtx | null>(null);
const useCite = () => {
  const v = useContext(Ctx);
  if (!v) throw new Error("citation context missing");
  return v;
};

const FACT_RE = /^F(\d+)$/;
const DATE_RE = /(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})/g;

function stripPart(label: string) {
  return label.replace(/\s*\(part \d+(?: of \d+)?\)/, "");
}

type CiteGroup = { key: string; name: string; parts: { cite: string; where: string }[] };

/** Group citations by source: "Facts ¶1, ¶3; Landlord and Tenant Act 1985, s 9A, s 11". */
function groupCites(cites: string[], auths: Record<string, AuthorityRef>): CiteGroup[] {
  const groups = new Map<string, CiteGroup>();
  for (const c of cites) {
    const f = FACT_RE.exec(c);
    const [jid, pid] = f ? ["F", c] : c.split(":");
    const a = f ? undefined : auths[jid];
    const name = f ? "Facts" : a ? a.name : c;
    const where = f ? `¶${f[1]}` : a && pid ? stripPart(a.passages[pid]?.label ?? pid) : "";
    const g = groups.get(jid) ?? { key: jid, name, parts: [] };
    if (!g.parts.some((p) => p.where === where)) g.parts.push({ cite: c, where });
    groups.set(jid, g);
  }
  return [...groups.values()];
}

export function citeLabel(cite: string, auths: Record<string, AuthorityRef>): string {
  const g = groupCites([cite], auths)[0];
  return g.parts[0]?.where ? `${g.name}, ${g.parts[0].where}` : g.name;
}

function Cites({ cites }: { cites: string[] }) {
  const { auths, open, active } = useCite();
  if (!cites.length) return null;
  return (
    <span className="font-sans text-[0.78em] text-ink-soft">
      {" "}
      {groupCites(cites, auths).map((g, gi) => (
        <span key={g.key}>
          {gi ? "; " : ""}
          {g.parts.length === 1 && !g.parts[0].where ? (
            <button type="button" className="cite cite-inline" aria-pressed={active === g.parts[0].cite}
              onClick={() => open(g.parts[0].cite)} aria-label={`Show source: ${g.name}`}>
              {g.name}
            </button>
          ) : (
            <>
              {g.name},{" "}
              {g.parts.map((p, i) => (
                <span key={p.cite}>
                  {i ? ", " : ""}
                  <button type="button" className="cite cite-inline" aria-pressed={active === p.cite}
                    onClick={() => open(p.cite)} aria-label={`Show source: ${g.name}, ${p.where}`}>
                    {p.where}
                  </button>
                </span>
              ))}
            </>
          )}
        </span>
      ))}
    </span>
  );
}

const NOTE_TONE: Record<string, string> = { unsupported: "text-unsupported", partial: "text-partial" };

const Line = memo(function Line({ st, lead, children }: { st: Statement; lead?: ReactNode; children?: ReactNode }) {
  const { ids } = useCite();
  return (
    <div id={ids.get(st)} className="grid scroll-mt-24 grid-cols-[1.6rem_1fr] gap-x-3 py-1.5">
      <SupportMark support={st.support} className="mt-[0.3rem]" />
      <div className={cn("min-w-0", st.support === "unsupported" && "text-ink-soft")}>
        {lead}
        {st.text}
        <Cites cites={st.citations} />
        {st.support_note && (st.support === "unsupported" || st.support === "partial") ? (
          <span className={cn("mt-1 block font-sans text-[13px] leading-snug", NOTE_TONE[st.support])}>
            {st.support === "unsupported" ? "Not supported: " : "Partly supported: "}
            {st.support_note}
          </span>
        ) : null}
        {children}
      </div>
    </div>
  );
});

function Quote({ entry }: { entry: PrecedentEntry }) {
  const { auths, open } = useCite();
  if (!entry.quote || !entry.quote_verified) return null;
  return (
    <blockquote className="quote mt-2">
      <p>“{entry.quote}”</p>
      <footer className="mt-1 flex flex-wrap items-center gap-1.5 font-sans text-[12.5px] text-ink-soft">
        <Check className="size-3.5 text-verified" aria-hidden="true" />
        Quoted verbatim from{" "}
        <button type="button" className="cite cite-inline" onClick={() => open(entry.quote_ref)}>
          {citeLabel(entry.quote_ref, auths)}
        </button>
      </footer>
    </blockquote>
  );
}

// ------------------------------------------------------------------ source panel
function SourcePanel({ cite, onClose }: { cite: string | null; onClose: () => void }) {
  const { auths, facts } = useCite();
  const fact = cite ? FACT_RE.exec(cite) : null;
  const [jid, pid] = cite && !fact ? cite.split(":") : ["", ""];
  const a = jid ? auths[jid] : undefined;
  const passage = a && pid ? a.passages[pid] : undefined;
  return (
    <Sheet open={Boolean(cite)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto overscroll-contain bg-paper p-0 sm:max-w-[34rem]">
        {fact ? (
          <>
            <SheetHeader className="border-b bg-vellum px-6 py-5">
              <SheetDescription>From your matter</SheetDescription>
              <SheetTitle className="font-serif text-xl">Facts, paragraph {fact[1]}</SheetTitle>
            </SheetHeader>
            <p className="brief px-6 py-6">{facts.get(cite!) ?? "This paragraph is not in the matter."}</p>
          </>
        ) : a ? (
          <>
            <SheetHeader className="border-b bg-vellum px-6 py-5">
              <SheetDescription>{KIND_LABEL[a.kind]}{a.court && a.kind !== "legislation" ? `, ${a.court}` : ""}</SheetDescription>
              <SheetTitle className="font-serif text-xl leading-snug">
                {a.name} {a.kind !== "legislation" ? <span className="font-normal">{a.citation}</span> : null}
              </SheetTitle>
            </SheetHeader>
            <div className="px-6 py-6">
              {passage ? (
                <>
                  <p className="text-sm font-semibold text-tape">{passage.label}</p>
                  <div className="brief mt-2 whitespace-pre-line text-[16px]">{passage.text}</div>
                </>
              ) : (
                <p className="text-muted-foreground">{a.summary || "Cited as a whole."}</p>
              )}
              {a.kind === "summary" ? (
                <p className="mt-6 rounded-md bg-partial-wash px-3 py-2 text-[13px] text-partial">
                  This is a paraphrased teaching summary, not the judgment. Check the official law report before
                  citing it.
                </p>
              ) : null}
              <div className="mt-6 flex flex-wrap gap-4 text-sm">
                {a.url ? (
                  <a href={a.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 font-semibold text-ink underline underline-offset-4">
                    Official text <ExternalLink className="size-3.5" />
                  </a>
                ) : null}
                <Link to={`/library/${a.id}`} className="font-semibold text-ink-soft underline underline-offset-4">
                  Open in library
                </Link>
              </div>
              {a.kind === "legislation" ? (
                <p className="mt-6 text-xs text-muted-foreground">
                  Revised text as published on legislation.gov.uk when your library was last updated. Check there for
                  amendments not yet in force or not yet applied.
                </p>
              ) : null}
            </div>
          </>
        ) : (
          <SheetHeader className="px-6 py-5">
            <SheetTitle>Source not available</SheetTitle>
          </SheetHeader>
        )}
      </SheetContent>
    </Sheet>
  );
}

// ------------------------------------------------------------------ the brief
const COVERAGE_TEXT = {
  none: "Your library has no authority that squarely addresses this issue.",
  weak: "Your library holds only limited authority on this issue.",
};

function Section({ id, title, children }: { id?: string; title: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 border-t pt-8">
      <h2 className="mb-3 text-ink">{title}</h2>
      {children}
    </section>
  );
}

function Issue({ issue }: { issue: IssueAnalysis }) {
  const authorities = (list: PrecedentEntry[]) =>
    list.length ? (
      list.map((e) => (
        <Line key={`${e.judgment_id}-${e.stance}`} st={e.proposition}
          lead={<span className="font-semibold text-ink">{e.case_name}{e.citation ? ` ${e.citation}` : ""}. </span>}>
          <Quote entry={e} />
        </Line>
      ))
    ) : (
      <p className="py-1.5 pl-[2.35rem] text-ink-soft">None found in your library.</p>
    );
  return (
    <Section id={issue.issue_id} title={<><span className="text-tape">{issue.issue_id}</span> {issue.question}</>}>
      {issue.coverage !== "good" ? (
        <div className={cn("mb-4 rounded-md border px-4 py-3 font-sans text-sm",
          issue.coverage === "none" ? "border-unsupported/40 bg-unsupported-wash text-unsupported" : "border-partial/40 bg-partial-wash text-partial")}>
          <strong className="font-semibold">{COVERAGE_TEXT[issue.coverage]}</strong>{" "}
          {issue.coverage_note} Research this issue independently, or upload the judgments you rely on to your library.
        </div>
      ) : null}
      <div className="grid gap-5">
        <div><h3>Authorities for your client</h3>{authorities(issue.supporting_precedents)}</div>
        <div><h3>Authorities for the other side</h3>{authorities(issue.opposing_precedents)}</div>
        <div><h3>Your client's argument</h3>{issue.supporting_argument.map((s, i) => <Line key={i} st={s} />)}</div>
        <div><h3>The other side's argument</h3>{issue.opposing_argument.map((s, i) => <Line key={i} st={s} />)}</div>
        <div className="rounded-md bg-vellum px-3 py-3 sm:px-4">
          <h3>Assessment</h3>
          <Line st={issue.assessment} />
        </div>
      </div>
    </Section>
  );
}

function latestDate(text: string): Date | null {
  let best: Date | null = null;
  for (const m of text.matchAll(DATE_RE)) {
    const d = new Date(`${m[1]} ${m[2]} ${m[3]}`);
    if (!Number.isNaN(d.getTime()) && (!best || d > best)) best = d;
  }
  return best;
}

function TimeLimits({ items }: { items: Statement[] }) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const rows = items
    .map((st) => ({ st, date: latestDate(st.text) }))
    .sort((a, b) => (a.date?.getTime() ?? Infinity) - (b.date?.getTime() ?? Infinity));
  return (
    <ol className="timeline">
      {rows.map(({ st, date }, i) => {
        const past = date ? date < today : false;
        const days = date ? Math.round((date.getTime() - today.getTime()) / 86_400_000) : null;
        return (
          <li key={i} className="grid grid-cols-[4.75rem_1fr] gap-x-4">
            <div className={cn("timeline-date font-sans", past && "text-unsupported")}>
              {date ? (
                <>
                  <span className="block text-2xl font-bold leading-none tabular-nums">{date.getDate()}</span>
                  <span className="block text-[12.5px]">{date.toLocaleDateString("en-GB", { month: "short", year: "numeric" })}</span>
                  <span className="mt-1 block text-[11.5px] font-semibold">
                    {past ? "Passed" : days === 0 ? "Today" : `In ${days} day${days === 1 ? "" : "s"}`}
                  </span>
                </>
              ) : (
                <span className="block text-[12.5px] text-muted-foreground">No date stated</span>
              )}
            </div>
            <Line st={st} />
          </li>
        );
      })}
    </ol>
  );
}

function EvidenceList({ items, runId }: { items: Statement[]; runId: number }) {
  const key = `precedent:evidence:${runId}`;
  const [done, setDone] = useState<Set<number>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(key) ?? "[]") as number[]);
    } catch {
      return new Set();
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify([...done]));
    } catch {
      /* storage unavailable */
    }
  }, [done, key]);
  return (
    <ul className="grid gap-1">
      {items.map((st, i) => (
        <li key={i} className="grid grid-cols-[1.75rem_1fr] items-start gap-x-2">
          <input type="checkbox" className="evidence-check mt-[0.6rem]" checked={done.has(i)}
            aria-label={`Obtained: ${st.text}`}
            onChange={(e) => {
              const checked = e.target.checked;
              setDone((prev) => {
                const next = new Set(prev);
                if (checked) next.add(i);
                else next.delete(i);
                return next;
              });
            }} />
          <div className={cn("transition-opacity", done.has(i) && "opacity-55")}><Line st={st} /></div>
        </li>
      ))}
    </ul>
  );
}

function Questions({ items }: { items: string[] }) {
  const copy = () => {
    const text = items.map((q, i) => `${i + 1}. ${q}`).join("\n");
    navigator.clipboard?.writeText(text).then(
      () => toast.success("Questions copied", { description: "Paste them into your email to the client." }),
      () => toast.error("Could not copy. Select the questions and copy them manually."),
    );
  };
  return (
    <div>
      <ol className="grid list-decimal gap-2 pl-6 marker:font-sans marker:text-sm marker:font-semibold marker:text-tape">
        {items.map((q, i) => <li key={i} className="pl-1">{q}</li>)}
      </ol>
      <button type="button" onClick={copy}
        className="mt-4 inline-flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 font-sans text-sm font-semibold text-ink hover:bg-accent">
        <Copy className="size-4" aria-hidden="true" /> Copy for an email
      </button>
    </div>
  );
}

const RELIABILITY = {
  high: { title: "Solid research starting point", tone: "border-verified/40 bg-verified-wash text-verified" },
  medium: { title: "Use with care", tone: "border-partial/40 bg-partial-wash text-partial" },
  low: { title: "Not reliable as it stands", tone: "border-unsupported/40 bg-unsupported-wash text-unsupported" },
  unchecked: { title: "Sources not checked", tone: "border-rule bg-vellum text-ink-soft" },
} as const;

/** One line a supervising lawyer reads first: how far this brief can be relied on, and why. */
function Reliability({ brief, jurisdiction }: { brief: RunResult["brief"]; jurisdiction?: string }) {
  const level = brief.reliability ?? "unchecked";
  const r = RELIABILITY[level] ?? RELIABILITY.unchecked;
  return (
    <div className={cn("mb-5 rounded-md border px-4 py-3 font-sans", r.tone)} role="status">
      <p className="text-[15px] font-bold">{r.title}{jurisdiction ? <span className="font-semibold text-ink-soft">{`. ${jurisdiction} law`}</span> : null}</p>
      {brief.reliability_reasons?.length ? (
        <ul className="mt-1 grid gap-0.5 text-[13px] text-ink">
          {brief.reliability_reasons.map((x, i) => <li key={i}>{x}</li>)}
        </ul>
      ) : null}
    </div>
  );
}

function CheckSummary({ result }: { result: RunResult }) {
  const s = result.support_report;
  if (!s || s.mode === "off") {
    return <p className="font-sans text-sm text-muted-foreground">Sources were not checked for this brief because no language model was configured.</p>;
  }
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 font-sans text-sm">
      <span className="text-ink-soft">{s.checked} statements checked against their sources:</span>
      <span className="inline-flex items-center gap-2"><SupportMark support="supported" /> {s.supported} verified</span>
      <span className="inline-flex items-center gap-2"><SupportMark support="partial" /> {s.partial} partly supported</span>
      <span className="inline-flex items-center gap-2"><SupportMark support="unsupported" /> {s.unsupported} not supported</span>
      {s.quotes?.verified ? <span className="text-muted-foreground">{s.quotes.verified} verbatim quotes matched</span> : null}
    </div>
  );
}

type Tab = { id: string; label: string; detail?: string; tone?: "none" | "weak" };

function DividerTabs({ tabs, current }: { tabs: Tab[]; current: string }) {
  return (
    <nav aria-label="Brief sections" className="divider-tabs">
      {tabs.map((t) => (
        <a key={t.id} href={`#${t.id}`} aria-current={current === t.id ? "location" : undefined}
          className={cn("divider-tab", t.tone && `divider-tab-${t.tone}`)}>
          <span className="font-sans text-[13px] font-bold">{t.label}</span>
          {t.detail ? <span className="line-clamp-2 font-sans text-[11.5px] leading-snug">{t.detail}</span> : null}
        </a>
      ))}
    </nav>
  );
}

const RAIL_LABEL: Record<string, string> = {
  supported: "Verified", partial: "Partly supported", unsupported: "Not supported", facts_only: "Facts", unchecked: "Not checked",
};

function VerificationRail({ items }: { items: { id: string; st: Statement }[] }) {
  return (
    <nav aria-label="Verification of each statement" className="verification-rail">
      {items.map(({ id, st }) => (
        <a key={id} href={`#${id}`} className={`rail-seg rail-${st.support}`} title={`${RAIL_LABEL[st.support]}: ${st.text.slice(0, 120)}`}>
          <span className="sr-only">{RAIL_LABEL[st.support]}: {st.text.slice(0, 80)}</span>
        </a>
      ))}
    </nav>
  );
}

function useCurrentSection(ids: string[]) {
  const [current, setCurrent] = useState(ids[0] ?? "");
  const key = ids.join("|");
  useEffect(() => {
    const els = key.split("|").map((id) => document.getElementById(id)).filter(Boolean) as HTMLElement[];
    if (!els.length) return;
    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setCurrent(visible[0].target.id);
      },
      { rootMargin: "-15% 0px -70% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [key]);
  return current;
}

export function BriefView({ result, runId }: { result: RunResult; runId: number }) {
  const b = result.brief;
  const [active, setActive] = useState<string | null>(null);
  const facts = useMemo(() => new Map(result.fact_paragraphs.map((p) => [p.ref, p.text])), [result.fact_paragraphs]);
  const ordered = useMemo(() => {
    const list: Statement[] = [...b.summary, ...b.facts];
    for (const i of b.issues) {
      list.push(...i.supporting_precedents.map((e) => e.proposition), ...i.opposing_precedents.map((e) => e.proposition),
        ...i.supporting_argument, ...i.opposing_argument, i.assessment);
    }
    list.push(...b.conclusion, ...(b.time_limits ?? []), ...(b.remedies ?? []), ...(b.evidence ?? []));
    return list.map((st, n) => ({ id: `st-${n}`, st }));
  }, [b]);
  const ids = useMemo(() => new Map(ordered.map(({ id, st }) => [st, id])), [ordered]);
  const ctx = useMemo<CiteCtx>(() => ({ auths: result.authorities, facts, open: setActive, active, ids }),
    [result.authorities, facts, active, ids]);
  const hasNext = Boolean(b.remedies?.length || b.time_limits?.length || b.evidence?.length || b.questions_for_client?.length);
  const tabs: Tab[] = useMemo(() => [
    { id: "summary", label: "Summary" },
    ...b.issues.map((i) => ({ id: i.issue_id, label: i.issue_id, detail: i.question,
      tone: i.coverage === "good" ? undefined : (i.coverage as "none" | "weak") })),
    { id: "conclusion", label: "Conclusion" },
    ...(hasNext ? [{ id: "next-steps", label: "Next steps" }] : []),
  ], [b, hasNext]);
  const current = useCurrentSection(tabs.map((t) => t.id));
  const repairs = b.warnings.filter((w) => !w.startsWith("Source check"));

  return (
    <Ctx.Provider value={ctx}>
      <div className="desk px-3 py-6 sm:px-6 lg:py-10">
        <div className="mx-auto grid max-w-[66rem] gap-4 lg:grid-cols-[0.75rem_minmax(0,48rem)] lg:gap-5 xl:grid-cols-[0.75rem_minmax(0,48rem)_11rem] xl:gap-x-5">
          <div className="hidden lg:block"><VerificationRail items={ordered} /></div>

          <article className="sheet brief min-w-0 text-ink">
            <Reliability brief={b} jurisdiction={(result as RunResult & { jurisdiction_check?: { matter_jurisdiction?: string } }).jurisdiction_check?.matter_jurisdiction} />
            <CheckSummary result={result} />
            <p className="mt-3 font-sans text-xs text-muted-foreground">
              Prepared for review by a qualified lawyer. Not legal advice. Select any citation to read the passage it
              relies on.
            </p>
            <nav aria-label="Jump to a section" className="-mx-1 mt-6 flex gap-1.5 overflow-x-auto px-1 pb-1 xl:hidden">
              {tabs.map((t) => (
                <a key={t.id} href={`#${t.id}`} className={cn("shrink-0 rounded-md border px-2.5 py-1 font-sans text-[13px] font-semibold",
                  t.tone === "none" ? "border-unsupported/40 text-unsupported" : t.tone === "weak" ? "border-partial/40 text-partial" : "text-ink-soft")}>
                  {t.label}
                </a>
              ))}
            </nav>
            <section id="summary" className="mt-8 scroll-mt-20">
              <h2 className="mb-3">Summary</h2>
              {b.summary.map((s, i) => <Line key={i} st={s} />)}
            </section>
            <Section title="Key facts">{b.facts.map((s, i) => <Line key={i} st={s} />)}</Section>
            {b.issues.map((i) => <Issue key={i.issue_id} issue={i} />)}
            <Section id="conclusion" title="Conclusion">{b.conclusion.map((s, i) => <Line key={i} st={s} />)}</Section>

            {hasNext ? (
              <section id="next-steps" className="next-steps scroll-mt-20">
                <h2 className="text-ink">Next steps</h2>
                {b.time_limits?.length ? (
                  <div className="mt-6">
                    <h3>Time limits</h3>
                    <TimeLimits items={b.time_limits} />
                    <p className="mt-2 font-sans text-[12.5px] text-muted-foreground">
                      Dates are worked out from the facts and the cited provision. Confirm each date and its counting
                      rule, and any extension (for example ACAS early conciliation), before relying on it.
                    </p>
                  </div>
                ) : null}
                {b.remedies?.length ? (
                  <div className="mt-7"><h3>What your client can claim</h3>{b.remedies.map((s, i) => <Line key={i} st={s} />)}</div>
                ) : null}
                {b.evidence?.length ? (
                  <div className="mt-7"><h3>Evidence to obtain</h3><EvidenceList items={b.evidence} runId={runId} /></div>
                ) : null}
                {b.questions_for_client?.length ? (
                  <div className="mt-7"><h3>Questions for the client</h3><Questions items={b.questions_for_client} /></div>
                ) : null}
              </section>
            ) : null}

            {repairs.length ? (
              <details className="mt-10 border-t pt-6 font-sans text-sm">
                <summary className="cursor-pointer font-semibold text-ink-soft">
                  {repairs.length} correction{repairs.length === 1 ? "" : "s"} made while checking citations
                </summary>
                <ul className="mt-3 grid list-disc gap-1.5 pl-5 text-muted-foreground">
                  {repairs.map((w, i) => <li key={i} className="break-words">{w}</li>)}
                </ul>
              </details>
            ) : null}
          </article>

          <div className="hidden xl:block"><DividerTabs tabs={tabs} current={current} /></div>
        </div>
      </div>
      <SourcePanel cite={active} onClose={() => setActive(null)} />
    </Ctx.Provider>
  );
}

// ------------------------------------------------------------------ debate
export function DebateView({ result }: { result: RunResult }) {
  const [active, setActive] = useState<string | null>(null);
  const facts = useMemo(() => new Map(result.fact_paragraphs.map((p) => [p.ref, p.text])), [result.fact_paragraphs]);
  const ctx = useMemo<CiteCtx>(() => ({ auths: result.authorities, facts, open: setActive, active, ids: new Map() }),
    [result.authorities, facts, active]);
  const questions = new Map(result.brief.issues.map((i) => [i.issue_id, i.question]));
  const rounds = [...new Set(result.turns.map((t) => t.round))];
  return (
    <Ctx.Provider value={ctx}>
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-8">
        <p className="max-w-[62ch] text-ink-soft">
          Two agents argued each issue from the same material, each keeping its own case in mind across rounds. Later
          rounds answer the other side's points. The brief is compiled from this exchange.
        </p>
        <div className="mt-8 hidden grid-cols-2 gap-6 font-sans text-sm font-bold md:grid">
          <span className="border-b-2 border-ink pb-2 text-ink">Your client's advocate</span>
          <span className="border-b-2 border-tape pb-2 text-tape">Opposing counsel</span>
        </div>
        {rounds.map((r) => (
          <section key={r} className="mt-6">
            <h2 className="font-serif text-lg font-semibold text-ink">Round {r}</h2>
            <div className="mt-3 grid gap-4 md:grid-cols-2 md:gap-6">
              {(["argument", "counter"] as const).map((side) => (
                <ul key={side} className="grid content-start gap-3" aria-label={side === "argument" ? "Your client's advocate" : "Opposing counsel"}>
                  {result.turns.filter((t) => t.round === r && t.speaker === side).flatMap((t) => t.points).map((p) => (
                    <li key={p.point_id} className={cn("rounded-md border bg-card px-4 py-3", side === "argument" ? "border-l-4 border-l-ink" : "border-l-4 border-l-tape")}>
                      <p className="font-sans text-xs text-muted-foreground">
                        <span className="md:hidden">{side === "argument" ? "Client's advocate. " : "Opposing counsel. "}</span>
                        {p.point_id} on {p.issue_id}: {questions.get(p.issue_id) ?? ""}
                        {p.responds_to ? `; answers ${p.responds_to}` : ""}
                      </p>
                      <p className="brief mt-1 text-[16px]">
                        {p.text}
                        <Cites cites={p.citations} />
                      </p>
                    </li>
                  ))}
                </ul>
              ))}
            </div>
          </section>
        ))}
      </div>
      <SourcePanel cite={active} onClose={() => setActive(null)} />
    </Ctx.Provider>
  );
}

export function FactsView({ result }: { result: RunResult }) {
  return (
    <div className="desk px-3 py-6 sm:px-6 lg:py-10">
      <div className="sheet brief mx-auto max-w-[48rem]">
        <p className="font-sans text-sm text-ink-soft">The facts as numbered for this brief. Citations such as “Facts ¶3” refer to these paragraphs.</p>
        <ol className="mt-6 grid gap-3">
          {result.fact_paragraphs.map((p) => (
            <li key={p.ref} className="grid grid-cols-[2.5rem_1fr] gap-2">
              <span className="font-sans text-sm font-semibold text-tape">¶{p.ref.slice(1)}</span>
              <span>
                {p.kind === "objective" ? <span className="font-sans text-xs font-semibold text-ink-soft">Client's objective. </span> : null}
                {p.text}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
