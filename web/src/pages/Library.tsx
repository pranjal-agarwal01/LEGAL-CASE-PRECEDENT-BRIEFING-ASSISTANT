import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Search, Trash2, Upload } from "lucide-react";
import { useDeferredValue, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";

import { PageHeader } from "@/components/Shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  api, AREA_LABEL, formatDate, KIND_LABEL, upload, type AuthorityDetail, type LibraryItem, type SearchHit,
} from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

type LibraryResponse = { items: LibraryItem[]; meta: { imported?: string; licence?: string } };
type Filter = "all" | "legislation" | "judgment" | "summary";

function UploadButton() {
  const ref = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  async function send(files: FileList) {
    setBusy(true);
    let ok = 0;
    for (const f of Array.from(files)) {
      try {
        await upload("/library/upload", f);
        ok += 1;
      } catch (e) {
        toast.error(`${f.name}: ${(e as Error).message}`);
      }
    }
    setBusy(false);
    if (ref.current) ref.current.value = "";
    if (ok) {
      toast.success(`${ok} judgment${ok === 1 ? "" : "s"} uploaded`, { description: "Indexing takes up to a minute per judgment." });
      qc.invalidateQueries({ queryKey: ["library"] });
    }
  }
  return (
    <>
      <input ref={ref} type="file" multiple accept=".pdf,.docx,.txt,.html,.htm,.md" className="sr-only"
        onChange={(e) => e.target.files?.length && send(e.target.files)} />
      <Button size="lg" className="h-10 bg-tape px-4 text-tape-ink hover:bg-tape/90" disabled={busy} onClick={() => ref.current?.click()}>
        <Upload /> {busy ? "Uploading…" : "Upload judgments"}
      </Button>
    </>
  );
}

function SearchResults({ q }: { q: string }) {
  const { data, isFetching } = useQuery({
    queryKey: ["search", q],
    queryFn: () => api<SearchHit[]>(`/library/search?q=${encodeURIComponent(q)}`),
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
            <Link to={`/library/${h.id}`} className="font-serif text-[1.05rem] font-semibold text-ink hover:text-tape">
              {h.name} {h.citation ? <span className="font-normal">{h.citation}</span> : null}
            </Link>
            <span className="ml-2 text-xs text-muted-foreground">{KIND_LABEL[h.kind]}</span>
            {h.passages.slice(0, 1).map((p) => (
              <p key={p.ref} className="mt-1.5 line-clamp-3 font-serif text-[15px] text-ink-soft">
                <span className="font-sans text-xs font-semibold text-tape">{p.label} </span>
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
  const [q, setQ] = useState("");
  const query = useDeferredValue(q.trim());
  const { data, isLoading } = useQuery({
    queryKey: ["library"],
    queryFn: () => api<LibraryResponse>("/library"),
    refetchInterval: (qq) => (qq.state.data?.items.some((i) => i.status === "processing") ? 3000 : false),
  });
  const items = (data?.items ?? []).filter((i) => filter === "all" || i.kind === filter);
  const uploads = (data?.items ?? []).filter((i) => i.id.startsWith("U")).length;

  return (
    <>
      <PageHeader
        title="Library"
        lede={
          <>
            {meta?.library.statutes ?? "…"} statutes and regulations for England and Wales, {uploads} judgment
            {uploads === 1 ? "" : "s"} uploaded by your firm, and {meta?.library.summaries ?? "…"} leading-case
            summaries. Briefs cite only what is here.
          </>
        }
      >
        <UploadButton />
      </PageHeader>

      <div className="px-4 py-6 sm:px-8">
        <div className="relative max-w-xl">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} className="h-11 bg-card pl-9 text-[15px]"
            placeholder="Search the law, e.g. landlord's duty to repair after notice" aria-label="Search the library" />
        </div>
        <SearchResults q={query} />

        <Tabs value={filter} onValueChange={(v) => setFilter(v as Filter)} className="mt-8 max-w-full overflow-x-auto">
          <TabsList variant="line">
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="legislation">Legislation</TabsTrigger>
            <TabsTrigger value="judgment">Your judgments</TabsTrigger>
            <TabsTrigger value="summary">Case summaries</TabsTrigger>
          </TabsList>
        </Tabs>

        {filter === "judgment" && uploads === 0 ? (
          <div className="max-w-xl py-8">
            <p className="text-ink-soft">
              Upload the judgments your firm relies on, as PDF or Word files. Precedent keeps the court's paragraph
              numbers, so a brief can cite paragraph 37 exactly. Use copies you are licensed to use, such as downloads
              from your law reports subscription.
            </p>
          </div>
        ) : null}

        {isLoading ? <p className="mt-6 text-muted-foreground">Loading…</p> : null}
        <ul className="mt-4 divide-y rounded-md border bg-card">
          {items.map((i) => (
            <li key={i.id} className="grid gap-1 px-4 py-3 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-4">
              <div className="min-w-0">
                <Link to={`/library/${i.id}`} className="font-serif text-[1.02rem] font-semibold text-ink hover:text-tape">
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
              <span className={cn("text-sm tabular-nums", i.status === "processing" ? "text-tape" : "text-muted-foreground")}>
                {i.status === "processing" ? (
                  <span className="inline-flex items-center gap-2"><span className="pulse size-2 rounded-full bg-tape" /> Indexing</span>
                ) : (
                  `${i.passages} ${i.kind === "legislation" ? "provisions" : "paragraphs"}`
                )}
              </span>
            </li>
          ))}
        </ul>
        {data?.meta?.imported ? (
          <p className="mt-6 max-w-[70ch] text-xs text-muted-foreground">
            Legislation is the revised text from legislation.gov.uk as of {formatDate(data.meta.imported)}.{" "}
            {data.meta.licence}
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
              <span className="font-sans text-sm font-semibold text-tape sm:pt-1 sm:text-right">{p.label}</span>
              <div className="whitespace-pre-line text-[16px]">{p.text}</div>
            </li>
          ))}
        </ol>
      </div>
    </>
  );
}
