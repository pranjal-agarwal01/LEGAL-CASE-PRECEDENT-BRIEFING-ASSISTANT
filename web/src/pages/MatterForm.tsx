import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { PageHeader } from "@/components/Shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, AREA_LABEL, upload, type Matter } from "@/lib/api";
import { useSession } from "@/lib/session";

type Draft = Pick<Matter, "title" | "reference" | "client_name" | "client_role" | "opponent" | "practice_area" | "jurisdiction" | "facts" | "objective">;
const EMPTY: Draft = { title: "", reference: "", client_name: "", client_role: "claimant", opponent: "", practice_area: "", jurisdiction: "England and Wales", facts: "", objective: "" };

export function MatterFormPage() {
  const { id } = useParams();
  const editing = Boolean(id);
  const { data } = useQuery({ queryKey: ["matter", id], queryFn: () => api<Matter>(`/matters/${id}`), enabled: editing });
  if (editing && !data) return <p className="p-8 text-muted-foreground">Loading…</p>;
  return <MatterForm key={id ?? "new"} initial={data ?? EMPTY} id={id} />;
}

function MatterForm({ initial, id }: { initial: Draft; id?: string }) {
  const [draft, setDraft] = useState<Draft>({
    title: initial.title, reference: initial.reference, client_name: initial.client_name,
    client_role: initial.client_role, opponent: initial.opponent, practice_area: initial.practice_area,
    jurisdiction: initial.jurisdiction || "England and Wales",
    facts: initial.facts, objective: initial.objective,
  });
  const [error, setError] = useState("");
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { meta } = useSession();
  const jurisdictions = meta?.jurisdictions ?? ["England and Wales"];
  const otherJurisdiction = !jurisdictions.includes(draft.jurisdiction);
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const words = draft.facts.trim() ? draft.facts.trim().split(/\s+/).length : 0;

  const save = useMutation({
    mutationFn: () =>
      id ? api<Matter>(`/matters/${id}`, { method: "PATCH", json: draft }) : api<Matter>("/matters", { method: "POST", json: draft }),
    onSuccess: (m) => {
      qc.invalidateQueries({ queryKey: ["matters"] });
      qc.invalidateQueries({ queryKey: ["matter", String(m.id)] });
      toast.success(id ? "Matter saved" : "Matter created");
      navigate(`/matters/${m.id}`);
    },
    onError: (e) => setError((e as Error).message),
  });
  const dirty = (Object.keys(draft) as (keyof Draft)[]).some((k) => draft[k] !== initial[k]);
  useEffect(() => {
    if (!dirty || save.isSuccess) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  });

  async function importDoc(file: File) {
    setImporting(true);
    try {
      const r = await upload<{ text: string; truncated: boolean }>("/extract-text", file);
      set("facts", draft.facts.trim() ? `${draft.facts.trim()}\n\n${r.text}` : r.text);
      toast.success(`Imported ${file.name}`, {
        description: r.truncated ? "The document was long, so only the first part was imported." : "Edit it down to the relevant facts.",
      });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (words < 25) {
      setError("Add the facts: at least a short paragraph about what happened.");
      return;
    }
    save.mutate();
  }

  return (
    <>
      <PageHeader
        title={id ? "Edit matter" : "New matter"}
        lede="Write the facts as you would in instructions to counsel. Precedent numbers each paragraph so the brief can cite it."
      />
      <form onSubmit={submit} className="grid max-w-5xl gap-10 px-4 py-8 sm:px-8 lg:grid-cols-[1fr_19rem]">
        <div className="grid gap-6">
          <div className="grid gap-1.5">
            <Label htmlFor="title">Matter name</Label>
            <Input id="title" required value={draft.title} onChange={(e) => set("title", e.target.value)}
              placeholder="e.g. Shah v Doyle" className="h-10 bg-card font-serif text-[1.05rem]" />
          </div>

          <div className="grid gap-1.5">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <Label htmlFor="facts">Facts</Label>
              <div className="flex items-center gap-3">
                <span className="text-xs tabular-nums text-muted-foreground">{words.toLocaleString("en-GB")} words</span>
                <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md,.html" className="sr-only" id="import"
                  onChange={(e) => e.target.files?.[0] && importDoc(e.target.files[0])} />
                <Button type="button" variant="outline" size="sm" disabled={importing} onClick={() => fileRef.current?.click()}>
                  <FileUp /> {importing ? "Reading…" : "Import from document"}
                </Button>
              </div>
            </div>
            <Textarea id="facts" value={draft.facts} onChange={(e) => set("facts", e.target.value)} rows={16}
              className="min-h-72 bg-card font-serif text-[1rem] leading-relaxed"
              placeholder={"1. On 2 March 2025 Ms Shah took a 12-month assured shorthold tenancy of Flat 4 from Mr Doyle.\n2. In April 2025 the bathroom ceiling began to leak. She told him in writing on 3 April and 9 May.\n3. …"} />
            <p className="text-xs text-muted-foreground">
              Use numbered paragraphs or blank lines between paragraphs. Include dates, who said what, and anything the
              other side disputes.
            </p>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="objective">What the client wants</Label>
            <Textarea id="objective" value={draft.objective} onChange={(e) => set("objective", e.target.value)} rows={3}
              className="bg-card" placeholder="e.g. Recover the cost of the laptop and hotel, and the return of her deposit." />
          </div>
        </div>

        <aside className="grid content-start gap-6 lg:border-l lg:pl-8">
          <div className="grid gap-1.5">
            <Label htmlFor="client_name">Client</Label>
            <Input id="client_name" required value={draft.client_name} onChange={(e) => set("client_name", e.target.value)}
              placeholder="e.g. Priya Shah" className="h-10 bg-card" />
          </div>
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-sm font-medium">Client is the</legend>
            <RadioGroup value={draft.client_role} onValueChange={(v) => set("client_role", v as Draft["client_role"])} className="flex gap-5">
              {(["claimant", "defendant"] as const).map((r) => (
                <div key={r} className="flex items-center gap-2">
                  <RadioGroupItem value={r} id={`role-${r}`} />
                  <Label htmlFor={`role-${r}`} className="font-normal capitalize">{r}</Label>
                </div>
              ))}
            </RadioGroup>
          </fieldset>
          <div className="grid gap-1.5">
            <Label htmlFor="opponent">Other side</Label>
            <Input id="opponent" value={draft.opponent} onChange={(e) => set("opponent", e.target.value)}
              placeholder="e.g. Mr Doyle" className="h-10 bg-card" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="jurisdiction">Governing law</Label>
            <Select value={otherJurisdiction ? "__other" : draft.jurisdiction}
              onValueChange={(v) => set("jurisdiction", v === "__other" ? "" : v)}>
              <SelectTrigger id="jurisdiction" className="h-10 w-full bg-card"><SelectValue /></SelectTrigger>
              <SelectContent>
                {jurisdictions.map((j) => <SelectItem key={j} value={j}>{j}</SelectItem>)}
                <SelectItem value="__other">Another jurisdiction</SelectItem>
              </SelectContent>
            </Select>
            {otherJurisdiction ? (
              <Input aria-label="Jurisdiction" value={draft.jurisdiction} onChange={(e) => set("jurisdiction", e.target.value)}
                placeholder="e.g. New York, United States" className="h-10 bg-card" />
            ) : null}
            <p className="text-xs text-muted-foreground">
              Precedent researches only this jurisdiction's legislation and judgments, and stops if the facts point
              elsewhere.
            </p>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="area">Practice area</Label>
            <Select value={draft.practice_area || undefined} onValueChange={(v) => set("practice_area", v)}>
              <SelectTrigger id="area" className="h-10 w-full bg-card">
                <SelectValue placeholder="Choose an area" />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(AREA_LABEL).map(([k, v]) => (
                  <SelectItem key={k} value={k}>{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="reference">Your reference</Label>
            <Input id="reference" value={draft.reference} onChange={(e) => set("reference", e.target.value)}
              placeholder="Optional, e.g. HR/2026/114" className="h-10 bg-card" />
          </div>
          {error ? <p role="alert" className="text-sm text-unsupported">{error}</p> : null}
          <div className="flex gap-2">
            <Button type="submit" size="lg" className="h-10 flex-1" disabled={save.isPending}>
              {save.isPending ? "Saving…" : id ? "Save matter" : "Create matter"}
            </Button>
            <Button type="button" variant="outline" size="lg" className="h-10" onClick={() => navigate(-1)}>
              Cancel
            </Button>
          </div>
        </aside>
      </form>
    </>
  );
}
