import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, MoreHorizontal, Pencil, Play, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { BriefView, DebateView, FactsView } from "@/components/BriefView";
import { RunProgress } from "@/components/RunProgress";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, AREA_LABEL, formatDate, type Blocked, type Matter, type Run, type RunResult } from "@/lib/api";
import { useSession } from "@/lib/session";

export function MatterPage() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { meta } = useSession();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const matter = useQuery({ queryKey: ["matter", id], queryFn: () => api<Matter>(`/matters/${id}`) });
  const runs = matter.data?.runs ?? [];
  const runId = Number(params.get("run")) || runs[0]?.id;

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api<Run>(`/runs/${runId}`),
    enabled: Boolean(runId),
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 1500 : false),
  });
  const status = run.data?.status;
  useEffect(() => {
    if (status === "done" || status === "failed" || status === "blocked") {
      qc.invalidateQueries({ queryKey: ["matter", id] });
      qc.invalidateQueries({ queryKey: ["matters"] });
    }
  }, [status, id, qc]);

  const start = useMutation({
    mutationFn: (override: boolean = false) =>
      api<{ id: number }>(`/matters/${id}/runs`, { method: "POST", json: { rounds: 2, override_jurisdiction: override } }),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ["matter", id] });
      setParams({ run: String(r.id) });
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: () => api(`/matters/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["matters"] });
      toast.success("Matter deleted");
      navigate("/matters");
    },
  });

  if (matter.isLoading) return <p className="p-8 text-muted-foreground">Loading…</p>;
  if (matter.error || !matter.data) return <p className="p-8 text-unsupported">This matter could not be found.</p>;
  const m = matter.data;
  const busy = status === "queued" || status === "running";

  return (
    <>
      <header className="border-b px-4 pb-5 pt-8 sm:px-8 lg:pt-12">
        <p className="text-sm text-muted-foreground">
          <Link to="/matters" className="hover:text-ink">Matters</Link>
          {m.reference ? <span>{` / ${m.reference}`}</span> : null}
        </p>
        <div className="mt-2 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <h1 className="font-serif text-3xl font-semibold tracking-tight text-ink sm:text-[2.15rem]">{m.title}</h1>
            <Parties matter={m} />
            <p className="mt-3 text-sm text-muted-foreground">
              {m.jurisdiction || "England and Wales"} law{m.practice_area ? `. ${AREA_LABEL[m.practice_area] ?? ""}` : ""}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button size="lg" className="h-10 bg-tape px-4 text-tape-ink hover:bg-tape/90" disabled={busy || start.isPending}
              onClick={() => start.mutate(false)}>
              <Play /> {runs.length ? "Prepare a new brief" : "Prepare brief"}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" className="size-10" aria-label="More actions"><MoreHorizontal /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem asChild>
                  <Link to={`/matters/${m.id}/edit`}><Pencil className="size-4" /> Edit facts and details</Link>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onSelect={() => setConfirmDelete(true)}>
                  <Trash2 className="size-4" /> Delete matter
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      {!runs.length ? (
        <div className="max-w-3xl px-4 py-10 sm:px-8">
          <h2 className="font-serif text-2xl font-semibold text-ink">No brief yet</h2>
          <p className="mt-2 text-ink-soft">
            Preparing a brief reads your facts, researches {meta?.library.statutes ?? "the"} statutes and your firm's
            judgments, argues both sides over two rounds, and checks every citation against its source.
          </p>
          <h3 className="mt-8 text-sm font-semibold text-ink-soft">Facts on file</h3>
          <p className="mt-2 line-clamp-[10] whitespace-pre-line font-serif leading-relaxed text-ink">{m.facts}</p>
          <Link to={`/matters/${m.id}/edit`} className="mt-3 inline-block text-sm font-semibold underline underline-offset-4">
            Edit facts
          </Link>
        </div>
      ) : null}

      {runs.length ? (
        <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3 sm:px-8">
          {runs.length > 1 ? (
            <Select value={String(runId)} onValueChange={(v) => setParams({ run: v })}>
              <SelectTrigger className="h-9 w-64 bg-card" aria-label="Choose a brief">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {runs.map((r) => (
                  <SelectItem key={r.id} value={String(r.id)}>
                    Brief of {formatDate(r.created_at, true)}{r.status === "failed" ? " (failed)" : r.status === "blocked" ? " (stopped)" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <span className="text-sm text-muted-foreground">Brief of {formatDate(runs[0].created_at, true)}</span>
          )}
          {status === "done" ? (
            <div className="ml-auto flex gap-2">
              <Button asChild variant="outline" size="sm">
                <a href={`/api/runs/${runId}/export.docx`}><Download /> Word</a>
              </Button>
              <Button asChild variant="outline" size="sm">
                <a href={`/api/runs/${runId}/export.md`}><Download /> Markdown</a>
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}

      {run.data && busy ? <RunProgress run={run.data} /> : null}

      {run.data?.status === "failed" ? (
        <div className="max-w-3xl px-4 py-10 sm:px-8">
          <h2 className="font-serif text-2xl font-semibold text-ink">This brief could not be prepared</h2>
          <p className="mt-2 break-words text-unsupported">{run.data.error || "An unknown error occurred."}</p>
          <p className="mt-4 text-ink-soft">Check the facts and prepare a new brief. If it keeps failing, contact your administrator.</p>
        </div>
      ) : null}

      {run.data?.status === "blocked" && run.data.result && "blocked" in run.data.result && run.data.result.blocked ? (
        <BlockedPanel blocked={run.data.result.blocked} matterId={m.id}
          onOverride={() => start.mutate(true)} busy={start.isPending} />
      ) : null}

      {run.data?.status === "done" && run.data.result && !("blocked" in run.data.result && run.data.result.blocked) ? (
        <Tabs value={params.get("tab") ?? "brief"} className="gap-0"
          onValueChange={(t) => setParams((p) => { const n = new URLSearchParams(p); n.set("tab", t); return n; }, { replace: true })}>
          <div className="border-b px-4 sm:px-8">
            <TabsList variant="line" className="h-11">
              <TabsTrigger value="brief">Brief</TabsTrigger>
              <TabsTrigger value="debate">Debate</TabsTrigger>
              <TabsTrigger value="facts">Numbered facts</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="brief"><BriefView result={run.data.result as RunResult} runId={run.data.id} /></TabsContent>
          <TabsContent value="debate"><DebateView result={run.data.result as RunResult} /></TabsContent>
          <TabsContent value="facts"><FactsView result={run.data.result as RunResult} /></TabsContent>
        </Tabs>
      ) : null}

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {m.title}?</DialogTitle>
            <DialogDescription>
              The facts and all {runs.length} brief{runs.length === 1 ? "" : "s"} for this matter will be permanently
              deleted. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild><Button variant="outline">Keep matter</Button></DialogClose>
            <Button variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending}>Delete matter</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** The parties set out as in a court heading: name, dotted leader, role; "and" between them. */
function Parties({ matter }: { matter: Matter }) {
  const client = { name: matter.client_name, role: matter.client_role === "defendant" ? "Defendant" : "Claimant", ours: true };
  const other = matter.opponent ? { name: matter.opponent, role: client.role === "Claimant" ? "Defendant" : "Claimant", ours: false } : null;
  const rows = client.role === "Claimant" ? [client, other] : [other, client];
  return (
    <div className="mt-4 font-serif text-[1.05rem] text-ink">
      <p className="mb-1 text-sm italic text-muted-foreground">Between</p>
      <div className="backsheet-parties gap-y-0.5">
        {rows.filter(Boolean).map((p, i) => (
          <div key={p!.role} className="contents">
            {i === 1 ? <p className="col-span-2 py-0.5 text-sm italic text-muted-foreground">and</p> : null}
            <span className="backsheet-leader">
              <span className={p!.ours ? "font-semibold" : undefined}>{p!.name}</span>
            </span>
            <span className="font-sans text-sm text-ink-soft">
              {p!.role}{p!.ours ? <span className="ml-1.5 rounded-sm bg-tape-wash px-1.5 py-0.5 text-[11.5px] font-semibold text-tape">Our client</span> : null}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Shown instead of a brief when the jurisdiction check stops a run: what was found, and what to do. */
function BlockedPanel({ blocked, matterId, onOverride, busy }: { blocked: Blocked; matterId: number; onOverride: () => void; busy: boolean }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const switchLaw = useMutation({
    mutationFn: () => api(`/matters/${matterId}`, { method: "PATCH", json: { jurisdiction: blocked.detected } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["matter", String(matterId)] });
      toast.success(`Governing law set to ${blocked.detected}`, { description: "Prepare the brief again once your library holds its authorities." });
    },
  });
  const mismatch = blocked.kind === "mismatch";
  return (
    <section className="desk px-3 py-8 sm:px-6">
      <div className="sheet mx-auto max-w-[44rem]">
        <p className="font-sans text-sm font-semibold text-unsupported">Research stopped before it started</p>
        <h2 className="mt-2 font-serif text-2xl font-semibold text-ink">
          {mismatch ? `These facts are governed by the law of ${blocked.detected}` : `Your library has no ${blocked.matter_jurisdiction} authorities`}
        </h2>
        <p className="mt-3 text-ink-soft">
          {mismatch
            ? `The matter is set to ${blocked.matter_jurisdiction}. Precedent will not answer a question about one legal system with another's law, so no brief was prepared.`
            : `Precedent researches only the legislation and judgments in your library for the matter's jurisdiction, and found none for ${blocked.matter_jurisdiction}.`}
        </p>
        {mismatch && blocked.reason ? (
          <p className="mt-4 rounded-md bg-vellum px-4 py-3 font-sans text-sm text-ink"><strong className="font-semibold">Why: </strong>{blocked.reason}</p>
        ) : null}
        <div className="mt-6 grid gap-3 font-sans">
          {mismatch ? (
            <button type="button" disabled={switchLaw.isPending} onClick={() => switchLaw.mutate()}
              className="rounded-md bg-ink px-4 py-2.5 text-left text-sm font-semibold text-paper hover:bg-ink/90">
              Set the governing law to {blocked.detected}
              <span className="block text-[12.5px] font-normal opacity-80">Then upload {blocked.detected} legislation and judgments to your library.</span>
            </button>
          ) : (
            <button type="button" onClick={() => navigate(`/library?upload=${encodeURIComponent(blocked.matter_jurisdiction)}`)}
              className="rounded-md bg-ink px-4 py-2.5 text-left text-sm font-semibold text-paper hover:bg-ink/90">
              Upload {blocked.matter_jurisdiction} legislation and judgments
              <span className="block text-[12.5px] font-normal opacity-80">Statutes, rules and the judgments you rely on, as PDF or Word.</span>
            </button>
          )}
          {mismatch ? (
            <button type="button" disabled={busy} onClick={onOverride}
              className="rounded-md border bg-card px-4 py-2.5 text-left text-sm font-semibold text-ink hover:bg-accent">
              Research under {blocked.matter_jurisdiction} law anyway
              <span className="block text-[12.5px] font-normal text-muted-foreground">
                Only if {blocked.matter_jurisdiction} law really governs, for example under a choice-of-law clause. This is recorded in your firm's activity log.
              </span>
            </button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
