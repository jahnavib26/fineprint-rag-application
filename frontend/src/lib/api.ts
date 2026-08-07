import { providerHeaders } from "./providers";
import type { Credentials, ProviderCatalogue } from "./providers";

// Types mirror backend/app/api/routes.py. Kept hand-written rather than
// generated so the shapes the UI actually depends on are visible in one place.

export type Clause = {
  id: string;
  number: string;
  heading: string;
  text: string;
  page: number;
  char_start: number;
  char_end: number;
  clause_type: string;
  document_id: string;
};

export type Citation = {
  clause: Clause;
  score: number;
  /** Set when this clause replaced the one retrieval actually matched. */
  supersedes: Clause | null;
  superseded_reason: string;
};

export type Verdict = {
  claim: string;
  citations: string[];
  verdict: "yes" | "partial" | "no";
  reason: string;
  load_bearing: boolean;
};

export type Answer = {
  status: "answered" | "not_covered";
  answer: string;
  citations: Citation[];
  nearest_topic: string;
  downgraded: boolean;
  downgrade_reason: string;
  verdicts: Verdict[];
  latency_ms: number;
  trace_id: string | null;
};

export type DocumentSummary = {
  id: string;
  lease_id: string;
  filename: string;
  kind: "original" | "addendum";
  signed_date: string | null;
  structure_confidence: number;
  strategy: string;
  clause_count: number;
};

export type DocumentText = {
  id: string;
  filename: string;
  full_text: string;
  clauses: Clause[];
};

// Set once at startup by App; every request picks up whatever is current.
let credentials: Credentials | null = null;
export function setCredentials(next: Credentials | null) {
  credentials = next;
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    // FastAPI puts the human-readable message in `detail`. Every 4xx this app
    // raises is written for the person reading it — a rejected key, a scanned
    // PDF, a mismatched embedding space — so unwrap it rather than showing
    // them the JSON envelope.
    const body = await response.text();
    let message = body;
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed?.detail === "string") message = parsed.detail;
    } catch {
      // Not JSON (a proxy error page, say) — show it as-is.
    }
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then(json<Record<string, unknown>>),

  documents: (leaseId: string) =>
    fetch(`/api/leases/${encodeURIComponent(leaseId)}/documents`).then(
      json<DocumentSummary[]>,
    ),

  documentText: (documentId: string) =>
    fetch(`/api/documents/${documentId}/text`).then(json<DocumentText>),

  providers: () => fetch("/api/providers").then(json<ProviderCatalogue>),

  ask: (leaseId: string, question: string) =>
    fetch(`/api/leases/${encodeURIComponent(leaseId)}/ask`, {
      method: "POST",
      headers: { "content-type": "application/json", ...providerHeaders(credentials) },
      body: JSON.stringify({ question }),
    }).then(json<Answer>),

  upload: (leaseId: string, file: File, kind: string, signedDate: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("lease_id", leaseId);
    form.append("kind", kind);
    if (signedDate) form.append("signed_date", signedDate);
    return fetch("/api/documents", {
      method: "POST",
      body: form,
      headers: providerHeaders(credentials),
    }).then(json<DocumentSummary>);
  },
};
