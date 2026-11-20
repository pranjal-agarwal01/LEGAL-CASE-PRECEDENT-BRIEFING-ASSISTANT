import { ExternalLink } from "lucide-react";
import { createContext, memo, useContext, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { SupportMark } from "@/components/Status";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { KIND_LABEL, type AuthorityRef, type IssueAnalysis, type RunResult, type Statement } from "@/lib/api";
import { cn } from "@/lib/utils";

// ------------------------------------------------------------------ citations
type CiteCtx = { auths: Record<string, AuthorityRef>; facts: Map<string, string>; open: (cite: string) => void; active: string | null };
const Ctx = createContext<CiteCtx | null>(null);
const useCite = () => {
  const v = useContext(Ctx);
  if (!v) throw new Error("citation context missing");
  return v;
};

const FACT_RE = /^F(\d+)$/;

export function citeLabel(cite: string, auths: Record<string, AuthorityRef>): string {
  const f = FACT_RE.exec(cite);
  if (f) return `Facts ¶${f[1]}`;
  const [jid, pid] = cite.split(":");
  const a = auths[jid];
  if (!a) return cite;
  const where = pid ? a.passages[pid]?.label?.replace(/\s*\(part \d+ of \d+\)/, "") : "";
  if (a.kind === "legislation") return where ? `${a.name}, ${where}` : a.name;
  return where ? `${a.name}, ${where}` : `${a.name} ${a.citation}`.trim();
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
    const where = f ? `¶${f[1]}` : a && pid ? (a.passages[pid]?.label ?? pid).replace(/\s*\(part \d+(?: of \d+)?\)/, "") : "";
    const g = groups.get(jid) ?? { key: jid, name, parts: [] };
    if (!g.parts.some((p) => p.where === where)) g.parts.push({ cite: c, where });
    groups.set(jid, g);
  }
  return [...groups.values()];
}

function Cites({ cites }: { cites: string[] }) {
  const { auths, open, active } = useCite();
  if (!cites.length) return null;
  const groups = groupCites(cites, auths);
  return (
    <span className="font-sans text-[0.78em] text-ink-soft">
      {" "}
      {groups.map((g, gi) => (
        <span key={g.key} className="whitespace-normal">
          {gi ? "; " : ""}
          {g.parts.length === 1 && !g.parts[0].where ? (
            <button type="button" className="cite cite-inline" aria-pressed={active === g.parts[0].cite} onClick={() => open(g.parts[0].cite)}
              aria-label={`Show source: ${g.name}`}>
              {g.name}
            </button>
          ) : (
            <>
              {g.name},{" "}
              {g.parts.map((p, i) => (
                <span key={p.cite}>
                  {i ? ", " : ""}
                  <button type="button" className="cite cite-inline" aria-pressed={active === p.cite} onClick={() => open(p.cite)}
                    aria-label={`Show source: ${g.name}, ${p.where}`}>
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

const NOTE_TONE: Record<string, string> = {
  unsupported: "text-unsupported",
  partial: "text-partial",
};

const Line = memo(function Line({ st, lead }: { st: Statement; lead?: ReactNode }) {
  return (
    <div className="grid grid-cols-[1.6rem_1fr] gap-x-3 py-1.5">
      <SupportMark support={st.support} className="mt-[0.3rem]" />
      <div className={cn(st.support === "unsupported" && "text-ink-soft")}>
        {lead}
        {st.text}
        <Cites cites={st.citations} />
        {st.support_note && (st.support === "unsupported" || st.support === "partial") ? (
          <span className={cn("mt-1 block font-sans text-[13px] leading-snug", NOTE_TONE[st.support])}>
            {st.support === "unsupported" ? "Not supported: " : "Partly supported: "}
            {st.support_note}
          </span>
        ) : null}
      </div>
    </div>
  );
});

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

// ------------------------------------------------------------------ brief
function Section({ id, title, children }: { id?: string; title: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 border-t pt-8">
      <h2 className="mb-3 text-ink">{title}</h2>
      {children}
    </section>
  );
}

const COVERAGE_TEXT = {
  none: "Your library has no authority that squarely addresses this issue.",
  weak: "Your library holds only limited authority on this issue.",
};

function Issue({ issue }: { issue: IssueAnalysis }) {
  const authorities = (list: IssueAnalysis["supporting_precedents"], empty: string) =>
    list.length ? (
      list.map((e) => (
        <Line key={e.judgment_id} st={e.proposition}
          lead={<span className="font-semibold text-ink">{e.case_name}{e.citation ? ` ${e.citation}` : ""}. </span>} />
      ))
    ) : (
      <p className="py-1.5 pl-[2.35rem] text-ink-soft">{empty}</p>
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
        <div>
          <h3>Authorities for your client</h3>
          {authorities(issue.supporting_precedents, "None found in your library.")}
        </div>
        <div>
          <h3>Authorities for the other side</h3>
          {authorities(issue.opposing_precedents, "None found in your library.")}
        </div>
        <div>
          <h3>Your client's argument</h3>
          {issue.supporting_argument.map((s, i) => <Line key={i} st={s} />)}
        </div>
        <div>
          <h3>The other side's argument</h3>
          {issue.opposing_argument.map((s, i) => <Line key={i} st={s} />)}
        </div>
        <div className="rounded-md bg-vellum px-3 py-3 sm:px-4">
          <h3>Assessment</h3>
          <Line st={issue.assessment} />
        </div>
      </div>
    </Section>
  );
}

function CheckSummary({ result }: { result: RunResult }) {
  const s = result.support_report;
  if (!s || s.mode === "off") {
    return (
      <p className="font-sans text-sm text-muted-foreground">
        Sources were not checked for this brief because no language model was configured.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 font-sans text-sm">
      <span className="text-ink-soft">{s.checked} statements checked against their sources:</span>
      <span className="inline-flex items-center gap-2"><SupportMark support="supported" /> {s.supported} verified</span>
      <span className="inline-flex items-center gap-2"><SupportMark support="partial" /> {s.partial} partly supported</span>
      <span className="inline-flex items-center gap-2"><SupportMark support="unsupported" /> {s.unsupported} not supported</span>
      {s.removed_precedents ? <span className="text-muted-foreground">{s.removed_precedents} unsupported authorities removed</span> : null}
    </div>
  );
}

export function BriefView({ result }: { result: RunResult }) {
  const b = result.brief;
  const [active, setActive] = useState<string | null>(null);
  const facts = useMemo(() => new Map(result.fact_paragraphs.map((p) => [p.ref, p.text])), [result.fact_paragraphs]);
  const ctx = useMemo<CiteCtx>(() => ({ auths: result.authorities, facts, open: setActive, active }), [result.authorities, facts, active]);
  const repairs = b.warnings.filter((w) => !w.startsWith("Source check"));

  return (
    <Ctx.Provider value={ctx}>
      <div className="grid gap-8 px-4 py-8 sm:px-8 xl:grid-cols-[13rem_minmax(0,46rem)] xl:gap-12">
        <nav aria-label="Issues" className="hidden xl:block">
          <div className="sticky top-6 grid gap-1 text-sm">
            <a href="#summary" className="rounded px-2 py-1.5 text-ink-soft hover:bg-accent hover:text-ink">Summary</a>
            {b.issues.map((i) => (
              <a key={i.issue_id} href={`#${i.issue_id}`} className="grid grid-cols-[1.8rem_1fr] rounded px-2 py-1.5 text-ink-soft hover:bg-accent hover:text-ink">
                <span className="font-semibold text-tape">{i.issue_id}</span>
                <span className="line-clamp-2">{i.question}</span>
              </a>
            ))}
            <a href="#conclusion" className="rounded px-2 py-1.5 text-ink-soft hover:bg-accent hover:text-ink">Conclusion</a>
          </div>
        </nav>

        <article className="brief min-w-0 text-ink">
          <CheckSummary result={result} />
          <p className="mt-3 font-sans text-xs text-muted-foreground">
            Prepared for review by a qualified lawyer. Not legal advice. Select any citation to read the passage it
            relies on.
          </p>
          <section id="summary" className="mt-8 scroll-mt-20">
            <h2 className="mb-3">Summary</h2>
            {b.summary.map((s, i) => <Line key={i} st={s} />)}
          </section>
          <Section title="Key facts">{b.facts.map((s, i) => <Line key={i} st={s} />)}</Section>
          {b.issues.map((i) => <Issue key={i.issue_id} issue={i} />)}
          <Section id="conclusion" title="Conclusion">{b.conclusion.map((s, i) => <Line key={i} st={s} />)}</Section>
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
      </div>
      <SourcePanel cite={active} onClose={() => setActive(null)} />
    </Ctx.Provider>
  );
}

// ------------------------------------------------------------------ debate
export function DebateView({ result }: { result: RunResult }) {
  const [active, setActive] = useState<string | null>(null);
  const facts = useMemo(() => new Map(result.fact_paragraphs.map((p) => [p.ref, p.text])), [result.fact_paragraphs]);
  const ctx = useMemo<CiteCtx>(() => ({ auths: result.authorities, facts, open: setActive, active }), [result.authorities, facts, active]);
  const questions = new Map(result.brief.issues.map((i) => [i.issue_id, i.question]));
  return (
    <Ctx.Provider value={ctx}>
      <div className="max-w-4xl px-4 py-8 sm:px-8">
        <p className="max-w-[62ch] text-ink-soft">
          Two agents argued each issue from the same material: one for your client, one for the other side. Later
          rounds answer the other side's points. The brief above is compiled from this exchange.
        </p>
        {result.turns.map((t) => (
          <section key={`${t.speaker}-${t.round}`} className="mt-8">
            <h2 className="font-serif text-lg font-semibold text-ink">
              Round {t.round}: {t.speaker === "argument" ? "your client's advocate" : "opposing counsel"}
            </h2>
            <ul className="mt-3 grid gap-3">
              {t.points.map((p) => (
                <li key={p.point_id} className={cn("rounded-md border bg-card px-4 py-3", t.speaker === "argument" ? "border-l-4 border-l-ink" : "border-l-4 border-l-tape")}>
                  <p className="font-sans text-xs text-muted-foreground">
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
          </section>
        ))}
      </div>
      <SourcePanel cite={active} onClose={() => setActive(null)} />
    </Ctx.Provider>
  );
}

export function FactsView({ result }: { result: RunResult }) {
  return (
    <div className="max-w-3xl px-4 py-8 sm:px-8">
      <p className="text-ink-soft">The facts as numbered for this brief. Citations such as "Facts ¶3" refer to these paragraphs.</p>
      <ol className="brief mt-6 grid gap-3">
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
  );
}
