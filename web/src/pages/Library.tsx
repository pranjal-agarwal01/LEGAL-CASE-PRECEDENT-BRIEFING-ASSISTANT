import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FileUp, Search, Trash2, Upload } from "lucide-react";
import { useDeferredValue, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { PageHeader } from "@/components/Shell";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api, AREA_LABEL, formatDate, KIND_LABEL, type AuthorityDetail, type LibraryItem, type SearchHit,
} from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

type LibraryResponse = { items: LibraryItem[]; meta: { source?: string; built?: string } };
type Filter = "all" | "legislation" | "judgment" | "uploads";
const PAGE = 150;

function UploadButton() {
  const ref = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const { meta } = useSession();
  const [params, setParams] = useSearchParams();
  const preset = params.get("upload");
  const [open, setOpen] = useState(Boolean(preset));
  const [jurisdiction, setJurisdiction] = useState(preset || "India");
  const [kind, setKind] = useState<"judgment" | "legislation">("judgment");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const jurisdictions = meta?.jurisdictions ?? ["India"];

  async function send() {
    setBusy(true);
    let ok = 0;
    for (const f of files) {
      try {
        const form = new FormData();
        form.append("file", f);
        form.append("jurisdiction", jurisdiction);
        form.append("kind", kind);
        await api("/library/upload", { method: "POST", body: form });
        ok += 1;
      } catch (e) {
        toast.error(`${f.name}: ${(e as Error).message}`);
      }
    }
    setBusy(false);
    if (ok) {
      toast.success(`${ok} document${ok === 1 ? "" : "s"} uploaded`, { description: "Indexing takes up to a minute each." });
      qc.invalidateQueries({ queryKey: ["library"] });
      setOpen(false);
      setFiles([]);
      if (preset) setParams({}, { replace: true });
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o && preset) setParams({}, { replace: true }); }}>
      <DialogTrigger asChild>
        <Button size="lg" className="h-10 bg-seal px-4 text-seal-ink hover:bg-seal/90"><Upload /> Upload to library</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Upload legislation or judgments</DialogTitle>
          <DialogDescription>
            Briefs research only documents from the matter's own jurisdiction, so say which law these are. Use copies
            your firm is licensed to use.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="up-j">Jurisdiction</Label>
            <Select value={jurisdiction} onValueChange={setJurisdiction}>
              <SelectTrigger id="up-j" className="h-10 w-full bg-card"><SelectValue /></SelectTrigger>
              <SelectContent>
                {[...new Set([...jurisdictions, jurisdiction])].map((j) => <SelectItem key={j} value={j}>{j}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-sm font-medium">These documents are</legend>
            <RadioGroup value={kind} onValueChange={(v) => setKind(v as "judgment" | "legislation")} className="flex gap-5">
              <div className="flex items-center gap-2"><RadioGroupItem value="judgment" id="k-j" /><Label htmlFor="k-j" className="font-normal">Judgments</Label></div>
              <div className="flex items-center gap-2"><RadioGroupItem value="legislation" id="k-l" /><Label htmlFor="k-l" className="font-normal">Legislation</Label></div>
            </RadioGroup>
          </fieldset>
          <div className="grid gap-1.5">
            <input ref={ref} type="file" multiple accept=".pdf,.docx,.txt,.html,.htm,.md" className="sr-only" id="up-files"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
            <Button type="button" variant="outline" onClick={() => ref.current?.click()}>
              <FileUp /> {files.length ? `${files.length} file${files.length === 1 ? "" : "s"} chosen` : "Choose PDF or Word files"}
            </Button>
            {files.length ? <p className="truncate text-xs text-muted-foreground">{files.map((f) => f.name).join(", ")}</p> : null}
          </div>
        </div>
        <DialogFooter>
          <Button disabled={!files.length || busy} onClick={send}>{busy ? "Uploading…" : "Upload"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SearchResults({ q, jurisdiction }: { q: string; jurisdiction: string }) {
  const { data, isFetching } = useQuery({
    queryKey: ["search", q, jurisdiction],
    queryFn: () => api<SearchHit[]>(`/library/search?q=${encodeURIComponent(q)}&jurisdiction=${encodeURIComponent(jurisdiction)}`),
    enabled: q.length >= 3,
    staleTime: 60_000,
  });
  if (q.length < 3) return null;
  return (
    <section aria-live="polite" className="mt-6">
      <h2 className="text-sm font-semibold text-ink-soft">{isFetching && !data ? "Searching…" : `Best matches for “${q}”`}</h2>
      <ul className="mt-3 grid gap-3">
        {(data ?? []).map((h) => (
          <li key={h.id} className="rounded-md border bg-card px-4 py-3">
            <Link to={`/library/${h.id}`} className="font-serif text-[1.05rem] font-semibold text-ink hover:text-seal">
              {h.name} {h.citation ? <span className="font-normal">{h.citation}</span> : null}
            </Link>
            <span className="ml-2 text-xs text-muted-foreground">{KIND_LABEL[h.kind]}</span>
            {h.passages.slice(0, 1).map((p) => (
              <p key={p.ref} className="mt-1.5 line-clamp-3 font-serif text-[15px] text-ink-soft">
                <span className="font-sans text-xs font-semibold text-seal">{p.label} </span>
                {p.text}
              </p>
            ))}
          </li>
        ))}
        {data && data.length === 0 ? <li className="text-muted-foreground">Nothing in your library matches.</li> : null}
      </ul>
    </section>
  );
}

export function LibraryPage() {
  const { meta } = useSession();
  const [filter, setFilter] = useState<Filter>("all");
  const [juris, setJuris] = useState("India");
  const [limit, setLimit] = useState(PAGE);
  const [q, setQ] = useState("");
  const query = useDeferredValue(q.trim());
  const { data, isLoading } = useQuery({
    queryKey: ["library"],
    queryFn: () => api<LibraryResponse>("/library"),
    refetchInterval: (qq) => (qq.state.data?.items.some((i) => i.status === "processing") ? 3000 : false),
  });
  const held = [...new Set((data?.items ?? []).map((i) => i.jurisdiction || "India"))].sort();
  const items = (data?.items ?? []).filter((i) => (filter === "all" || (filter === "uploads" ? i.id.startsWith("U") : i.kind === filter))
    && (i.jurisdiction || "India") === juris);
  const uploads = (data?.items ?? []).filter((i) => i.id.startsWith("U")).length;

  return (
    <>
      <PageHeader
        title="Library"
        lede={
          <>
            {meta?.library.judgments ?? "…"} Supreme Court of India judgments on property and land,{" "}
            {meta?.library.statutes ?? "…"} Acts, and {uploads} document{uploads === 1 ? "" : "s"} you uploaded.
            Briefs cite only what is here.
            {meta?.library.loading ? " The library is still loading into a new database; search grows as it fills." : ""}
          </>
        }
      >
        <UploadButton />
      </PageHeader>

      <div className="px-4 py-6 sm:px-8">
        <div className="relative max-w-xl">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} className="h-11 bg-card pl-9 text-[15px]"
            placeholder="Search the law, e.g. adverse possession by a co-owner" aria-label="Search the library" />
        </div>
        <SearchResults q={query} jurisdiction={juris} />

        <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
        <Select value={juris} onValueChange={setJuris}>
          <SelectTrigger className="h-9 w-56 bg-card" aria-label="Jurisdiction"><SelectValue /></SelectTrigger>
          <SelectContent>
            {[...new Set(["India", ...held])].map((j) => (
              <SelectItem key={j} value={j}>{j} ({(data?.items ?? []).filter((i) => (i.jurisdiction || "India") === j).length})</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Tabs value={filter} onValueChange={(v) => { setFilter(v as Filter); setLimit(PAGE); }} className="max-w-full overflow-x-auto [scrollbar-width:none]">
          <TabsList variant="line">
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="legislation">Legislation</TabsTrigger>
            <TabsTrigger value="judgment">Judgments</TabsTrigger>
            <TabsTrigger value="uploads">Your uploads</TabsTrigger>
          </TabsList>
        </Tabs>
        </div>

        {filter === "uploads" && uploads === 0 ? (
          <div className="max-w-xl py-8">
            <p className="text-ink-soft">
              Upload High Court judgments, state Acts or rent laws you rely on, as PDF or Word files. Precedent keeps
              the court's paragraph numbers, so a brief can cite paragraph 37 exactly.
            </p>
          </div>
        ) : null}

        {isLoading ? <p className="mt-6 text-muted-foreground">Loading…</p> : null}
        <ul className="mt-4 divide-y rounded-md border bg-card">
          {items.slice(0, limit).map((i) => (
            <li key={i.id} className="grid gap-1 px-4 py-3 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-4">
              <div className="min-w-0">
                <Link to={`/library/${i.id}`} className="font-serif text-[1.02rem] font-semibold text-ink hover:text-seal">
                  {i.name} {i.citation && i.kind !== "legislation" ? <span className="font-normal">{i.citation}</span> : null}
                </Link>
                <p className="text-[13px] text-muted-foreground">
                  {KIND_LABEL[i.kind]}
                  {i.court && i.kind !== "legislation" ? `, ${i.court}` : ""}
                  {i.areas?.filter((a) => AREA_LABEL[a]).length ? `. ${i.areas.filter((a) => AREA_LABEL[a]).map((a) => AREA_LABEL[a]).join(", ")}` : ""}
                  {i.uploaded_by ? `. Uploaded by ${i.uploaded_by}` : ""}
                </p>
                {i.status === "failed" ? <p className="text-[13px] text-unsupported">Could not index: {i.error}</p> : null}
              </div>
              <span className={cn("text-sm tabular-nums", i.status === "processing" ? "text-seal" : "text-muted-foreground")}>
                {i.status === "processing" ? (
                  <span className="inline-flex items-center gap-2"><span className="pulse size-2 rounded-full bg-seal" /> Indexing</span>
                ) : (
                  `${i.passages} ${i.kind === "legislation" ? "provisions" : "paragraphs"}`
                )}
              </span>
            </li>
          ))}
        </ul>
        {items.length > limit ? (
          <Button variant="outline" className="mt-4" onClick={() => setLimit((n) => n + PAGE * 4)}>
            Show more ({items.length - limit} not shown)
          </Button>
        ) : null}
        {data?.meta?.source ? (
          <p className="mt-6 max-w-[70ch] text-xs text-muted-foreground">
            {data.meta.source}. Library built {data.meta.built ? formatDate(data.meta.built) : ""}. Check every
            authority against the official report before relying on it.
          </p>
        ) : null}
      </div>
    </>
  );
}

export function AuthorityPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({ queryKey: ["authority", id], queryFn: () => api<AuthorityDetail>(`/library/${id}`) });
  const [q, setQ] = useState("");
  const remove = useMutation({
    mutationFn: () => api(`/library/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["library"] });
      toast.success("Judgment removed from your library");
      history.back();
    },
  });
  if (isLoading) return <p className="p-8 text-muted-foreground">Loading…</p>;
  if (error || !data) return <p className="p-8 text-unsupported">Not found.</p>;
  const needle = q.trim().toLowerCase();
  const passages = needle ? data.passages.filter((p) => `${p.label} ${p.title ?? ""} ${p.text}`.toLowerCase().includes(needle)) : data.passages;

  return (
    <>
      <header className="border-b px-4 pb-6 pt-8 sm:px-8 lg:pt-12">
        <p className="text-sm text-muted-foreground"><Link to="/library" className="hover:text-ink">Library</Link> / {KIND_LABEL[data.kind]}</p>
        <h1 className="mt-2 max-w-[40ch] font-serif text-3xl font-semibold tracking-tight text-ink">
          {data.name} {data.kind !== "legislation" && data.citation ? <span className="font-normal">{data.citation}</span> : null}
        </h1>
        <p className="mt-2 text-ink-soft">
          {[data.court && data.kind !== "legislation" ? data.court : "", data.date ? `Dated ${formatDate(data.date)}` : ""].filter(Boolean).join(". ")}
        </p>
        {data.summary ? <p className="mt-3 max-w-[70ch] font-serif text-ink">{data.summary}</p> : null}
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
          {data.url ? (
            <a href={data.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 font-semibold underline underline-offset-4">
              Official text <ExternalLink className="size-3.5" />
            </a>
          ) : null}
          {data.id.startsWith("U") ? (
            <Button variant="outline" size="sm" disabled={remove.isPending} onClick={() => {
              if (window.confirm(`Remove ${data.name} from your library? Briefs already prepared keep their citations.`)) remove.mutate();
            }}>
              <Trash2 /> Remove from library
            </Button>
          ) : null}
        </div>
        {data.id.startsWith("U") ? <UploadSettings item={data} /> : (
          <p className="mt-3 text-sm text-muted-foreground">{data.jurisdiction} law.</p>
        )}
        {data.kind === "summary" ? (
          <p className="mt-4 max-w-[70ch] rounded-md bg-partial-wash px-3 py-2 text-sm text-partial">
            A paraphrased teaching summary, not the judgment itself. Check the official law report before citing it.
          </p>
        ) : null}
      </header>
      <div className="px-4 py-6 sm:px-8">
        {data.passages.length > 12 ? (
          <Input value={q} onChange={(e) => setQ(e.target.value)} className="mb-6 h-10 max-w-sm bg-card"
            placeholder={data.kind === "legislation" ? "Find a section" : "Find a paragraph"} aria-label="Filter passages" />
        ) : null}
        <ol className="brief grid max-w-[50rem] gap-5">
          {passages.map((p) => (
            <li key={p.pid} id={p.pid} className="grid scroll-mt-6 gap-x-5 sm:grid-cols-[6.5rem_1fr]">
              <span className="font-sans text-sm font-semibold text-seal sm:pt-1 sm:text-right">{p.label}</span>
              <div className="whitespace-pre-line text-[16px]">{p.text}</div>
            </li>
          ))}
        </ol>
      </div>
    </>
  );
}

/** An upload's jurisdiction and type decide which matters may cite it, so the firm can correct them. */
function UploadSettings({ item }: { item: AuthorityDetail }) {
  const qc = useQueryClient();
  const { meta } = useSession();
  const save = useMutation({
    mutationFn: (body: Record<string, string>) => api(`/library/${item.id}`, { method: "PATCH", json: body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["authority", item.id] });
      qc.invalidateQueries({ queryKey: ["library"] });
      toast.success("Saved");
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const options = [...new Set([...(meta?.jurisdictions ?? []), item.jurisdiction])];
  return (
    <div className="mt-4 flex flex-wrap items-end gap-4">
      <div className="grid gap-1">
        <Label htmlFor="u-j" className="text-xs text-muted-foreground">Jurisdiction</Label>
        <Select value={item.jurisdiction} onValueChange={(v) => save.mutate({ jurisdiction: v })}>
          <SelectTrigger id="u-j" className="h-9 w-56 bg-card"><SelectValue /></SelectTrigger>
          <SelectContent>{options.map((j) => <SelectItem key={j} value={j}>{j}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <div className="grid gap-1">
        <Label htmlFor="u-k" className="text-xs text-muted-foreground">Type</Label>
        <Select value={item.kind} onValueChange={(v) => save.mutate({ kind: v })}>
          <SelectTrigger id="u-k" className="h-9 w-40 bg-card"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="judgment">Judgment</SelectItem>
            <SelectItem value="legislation">Legislation</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
