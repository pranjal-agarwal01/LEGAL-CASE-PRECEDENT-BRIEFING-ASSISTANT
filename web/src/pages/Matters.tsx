import { useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/Shell";
import { StatusText } from "@/components/Status";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, AREA_LABEL, formatDate, type MatterRow } from "@/lib/api";
import { useSession } from "@/lib/session";

export function MattersPage() {
  const { meta } = useSession();
  const [q, setQ] = useState("");
  const query = useDeferredValue(q.trim().toLowerCase());
  const { data, isLoading, error } = useQuery({ queryKey: ["matters"], queryFn: () => api<MatterRow[]>("/matters") });
  const rows = (data ?? []).filter(
    (m) => !query || `${m.title} ${m.reference} ${m.client_name} ${m.opponent}`.toLowerCase().includes(query),
  );

  return (
    <>
      <PageHeader
        title="Matters"
        lede="Each matter holds the facts you are instructed on and every brief prepared for it."
      >
        {data?.length ? (
          <Button asChild size="lg" className="h-10 bg-tape px-4 text-tape-ink hover:bg-tape/90">
            <Link to="/matters/new">
              <Plus /> New matter
            </Link>
          </Button>
        ) : null}
      </PageHeader>

      {meta && !meta.llm_ready ? (
        <p className="mx-4 mt-6 rounded-md border border-partial/40 bg-partial-wash px-4 py-3 text-sm text-partial sm:mx-8">
          No language model is configured on this server, so briefs use the basic offline method. Set LLM_PROVIDER
          and its key to enable full analysis.
        </p>
      ) : null}

      <div className="px-4 py-6 sm:px-8">
        {data && data.length > 6 ? (
          <div className="relative mb-4 max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Find a matter, client or reference"
              aria-label="Find a matter"
              className="h-10 bg-card pl-9"
            />
          </div>
        ) : null}

        {isLoading ? <p className="text-muted-foreground">Loading matters…</p> : null}
        {error ? <p className="text-unsupported">Could not load matters: {(error as Error).message}</p> : null}

        {data && data.length === 0 ? (
          <div className="max-w-xl py-10">
            <h2 className="font-serif text-2xl font-semibold text-ink">Start with a matter</h2>
            <p className="mt-2 text-ink-soft">
              Add the facts as you would in instructions to counsel: who the parties are, what happened and when, and
              what your client wants. You can paste them or import a Word or PDF document.
            </p>
            <Button asChild className="mt-6 h-10 bg-tape px-4 text-tape-ink hover:bg-tape/90">
              <Link to="/matters/new">
                <Plus /> New matter
              </Link>
            </Button>
          </div>
        ) : null}

        {rows.length > 0 ? (
          <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_19rem]">
          <ComingUp matters={data ?? []} />
          <div className="overflow-x-auto rounded-md border bg-card xl:order-first">
            <table className="w-full text-left text-sm">
              <thead className="border-b bg-vellum/60 text-[13px] text-muted-foreground">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">Matter</th>
                  <th className="hidden px-4 py-2.5 font-semibold sm:table-cell">Acting for</th>
                  <th className="hidden px-4 py-2.5 font-semibold lg:table-cell">Area</th>
                  <th className="px-4 py-2.5 font-semibold">Latest brief</th>
                  <th className="hidden px-4 py-2.5 text-right font-semibold md:table-cell">Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((m) => (
                  <tr key={m.id} className="border-b last:border-0 hover:bg-accent/60">
                    <td className="px-4 py-3">
                      <Link to={`/matters/${m.id}`} className="font-serif text-[1.02rem] font-semibold text-ink hover:text-tape">
                        {m.title}
                      </Link>
                      {m.reference ? <span className="ml-2 text-xs text-muted-foreground">{m.reference}</span> : null}
                      <span className="block text-[13px] text-muted-foreground sm:hidden">For {m.client_name}</span>
                    </td>
                    <td className="hidden px-4 py-3 text-ink-soft sm:table-cell">
                      {m.client_name} <span className="text-muted-foreground">({m.client_role})</span>
                    </td>
                    <td className="hidden px-4 py-3 text-ink-soft lg:table-cell">{AREA_LABEL[m.practice_area] ?? "—"}</td>
                    <td className="px-4 py-3">
                      {m.last_run ? <StatusText run={m.last_run} /> : <span className="text-muted-foreground">None yet</span>}
                    </td>
                    <td className="hidden px-4 py-3 text-right tabular-nums text-muted-foreground md:table-cell">{formatDate(m.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </div>
        ) : null}
      </div>
    </>
  );
}

/** Time limits from each matter's latest brief, soonest first, so deadlines are the first thing a lawyer sees. */
function ComingUp({ matters }: { matters: MatterRow[] }) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const items = matters
    .flatMap((m) => (m.last_run?.deadlines ?? []).map((d) => ({ ...d, matter: m, when: new Date(`${d.date}T00:00:00`) })))
    .sort((a, b) => a.when.getTime() - b.when.getTime());
  const upcoming = items.filter((d) => d.when >= today);
  const passed = items.filter((d) => d.when < today).slice(-2);
  return (
    <aside aria-labelledby="coming-up" className="rounded-md border bg-card p-4">
      <h2 id="coming-up" className="font-serif text-lg font-semibold text-ink">Coming up</h2>
      {items.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">
          Time limits from your briefs appear here, soonest first, once a brief states a date.
        </p>
      ) : (
        <ol className="mt-3 grid gap-3">
          {[...passed, ...upcoming.slice(0, 6)].map((d, i) => {
            const days = Math.round((d.when.getTime() - today.getTime()) / 86_400_000);
            const late = days < 0;
            const soon = !late && days <= 14;
            return (
              <li key={i} className="grid grid-cols-[3.25rem_1fr] gap-3">
                <div className={`rounded-md border px-1 py-1.5 text-center leading-none ${late ? "border-unsupported/40 bg-unsupported-wash text-unsupported" : soon ? "border-tape/40 bg-tape-wash text-tape" : "text-ink"}`}>
                  <span className="block text-xl font-bold tabular-nums">{d.when.getDate()}</span>
                  <span className="mt-1 block text-[11px] font-semibold">{d.when.toLocaleDateString("en-GB", { month: "short" })}</span>
                </div>
                <div className="min-w-0">
                  <Link to={`/matters/${d.matter.id}?tab=brief#next-steps`} className="font-serif font-semibold text-ink hover:text-tape">
                    {d.matter.title}
                  </Link>
                  <p className="line-clamp-2 text-[13px] text-ink-soft">{d.text}</p>
                  <p className={`text-[12px] font-semibold ${late ? "text-unsupported" : soon ? "text-tape" : "text-muted-foreground"}`}>
                    {late ? `Passed ${-days} day${days === -1 ? "" : "s"} ago` : days === 0 ? "Today" : `In ${days} day${days === 1 ? "" : "s"}`}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </aside>
  );
}
