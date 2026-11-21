export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function messageFrom(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0]?.msg) {
      const field = Array.isArray(d[0].loc) ? d[0].loc[d[0].loc.length - 1] : "";
      return `${field ? `${field}: ` : ""}${String(d[0].msg).replace(/^Value error, /, "")}`;
    }
  }
  return fallback;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...rest,
    headers: {
      "X-Requested-With": "precedent",
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, messageFrom(body, `Request failed (${res.status}).`));
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export async function upload<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  return api<T>(path, { method: "POST", body: form });
}

// ---------------------------------------------------------------- types
export type Me = {
  id: number;
  email: string;
  name: string;
  role: "admin" | "member";
  firm: string;
  firm_id: number;
  must_change_password: boolean;
  include_summaries: boolean;
};

export type Meta = {
  signup: boolean;
  model: string | null;
  provider: string;
  llm_ready: boolean;
  search_mode: string;
  runs_per_day: number;
  practice_areas: { key: string; label: string }[];
  jurisdictions: string[];
  library: { statutes: number; judgments: number; passages: number; loading: boolean; source: string; built: string };
};

export type Deadline = { date: string; text: string; support: Support };
export type RunSummary = {
  id: number;
  status: RunStatus;
  created_at: string;
  issues?: number;
  unsupported?: number;
  reliability?: Reliability;
  deadlines?: Deadline[];
};
export type Reliability = "high" | "medium" | "low" | "unchecked";
export type RunStatus = "queued" | "running" | "done" | "failed" | "blocked";

export type MatterRow = {
  id: number;
  reference: string;
  title: string;
  client_name: string;
  client_role: "claimant" | "defendant";
  opponent: string;
  practice_area: string;
  jurisdiction: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  last_run?: RunSummary;
};

export type Matter = MatterRow & {
  facts: string;
  objective: string;
  runs?: { id: number; status: RunStatus; created_at: string; seconds: number; model: string }[];
};

export type Support = "supported" | "partial" | "unsupported" | "unchecked" | "facts_only";
export type Statement = { text: string; citations: string[]; support: Support; support_note: string };
export type PrecedentEntry = {
  judgment_id: string;
  case_name: string;
  citation: string;
  stance: "supporting" | "opposing";
  proposition: Statement;
  quote: string;
  quote_ref: string;
  quote_verified: boolean;
};
export type IssueAnalysis = {
  issue_id: string;
  question: string;
  coverage: "good" | "weak" | "none";
  coverage_note: string;
  supporting_precedents: PrecedentEntry[];
  opposing_precedents: PrecedentEntry[];
  supporting_argument: Statement[];
  opposing_argument: Statement[];
  assessment: Statement;
};
export type Brief = {
  case_id: string;
  title: string;
  acting_for: string;
  summary: Statement[];
  facts: Statement[];
  issues: IssueAnalysis[];
  conclusion: Statement[];
  remedies: Statement[];
  time_limits: Statement[];
  evidence: Statement[];
  questions_for_client: string[];
  reliability: Reliability;
  reliability_reasons: string[];
  warnings: string[];
};
export type AuthorityRef = {
  id: string;
  kind: "legislation" | "judgment" | "summary";
  name: string;
  citation: string;
  court: string;
  url: string;
  date: string;
  summary: string;
  note: string;
  passages: Record<string, { label: string; text: string }>;
};
export type TraceEvent = { t: number; agent: string; action: string; detail: string; stage?: string; round?: number };
export type DebatePoint = { point_id: string; issue_id: string; text: string; citations: string[]; responds_to: string | null };
export type RunResult = {
  brief: Brief;
  raw_report: Record<string, unknown>;
  final_report: { total_citations: number; valid_citations: number; claim_coverage: number };
  support_report: {
    checked: number;
    supported: number;
    partial: number;
    unsupported: number;
    removed_precedents: number;
    mode: string;
    quotes?: { quotes: number; verified: number; removed: number };
  };
  fact_paragraphs: { ref: string; kind: string; text: string }[];
  turns: { speaker: "argument" | "counter"; round: number; points: DebatePoint[] }[];
  board: { issues: { id: string; question: string; raised_by: string; doctrine: string | null }[] };
  warnings: string[];
  mode: string;
  llm_calls: number;
  seconds: number;
  authorities: Record<string, AuthorityRef>;
  search_mode: string;
};
export type Blocked = {
  kind: "mismatch" | "no_library";
  message: string;
  matter_jurisdiction: string;
  detected: string | null;
  confidence: string;
  reason: string;
  cues: string[];
  library_count: number;
};
export type Run = {
  id: number;
  matter_id: number;
  status: RunStatus;
  error: string;
  model: string;
  rounds: number;
  events: TraceEvent[];
  result: (RunResult & { blocked?: undefined }) | { blocked: Blocked } | null;
  seconds: number;
  llm_calls: number;
  created_at: string;
};

export type LibraryItem = {
  id: string;
  kind: "legislation" | "judgment" | "summary";
  jurisdiction: string;
  name: string;
  citation: string;
  court: string;
  year: number | null;
  areas: string[];
  passages: number;
  url?: string;
  date?: string;
  status?: "processing" | "ready" | "failed";
  error?: string;
  uploaded_by?: string | null;
  filename?: string;
  doctrines: string[];
};
export type AuthorityDetail = {
  id: string;
  kind: LibraryItem["kind"];
  jurisdiction: string;
  name: string;
  citation: string;
  court: string;
  date: string;
  summary: string;
  note: string;
  url: string;
  status?: string;
  passages: { pid: string; label: string; title?: string; text: string }[];
};
export type SearchHit = {
  id: string;
  kind: LibraryItem["kind"];
  name: string;
  citation: string;
  score: number;
  passages: { ref: string; label: string; text: string }[];
};

export const AREA_LABEL: Record<string, string> = {
  property: "Property & land",
};

export const KIND_LABEL: Record<string, string> = {
  legislation: "Legislation",
  judgment: "Judgment",
  summary: "Case summary",
};

export function formatDate(iso: string, withTime = false): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}
