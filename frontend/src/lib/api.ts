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

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
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

  ask: (leaseId: string, question: string) =>
    fetch(`/api/leases/${encodeURIComponent(leaseId)}/ask`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question }),
    }).then(json<Answer>),

  upload: (leaseId: string, file: File, kind: string, signedDate: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("lease_id", leaseId);
    form.append("kind", kind);
    if (signedDate) form.append("signed_date", signedDate);
    return fetch("/api/documents", { method: "POST", body: form }).then(
      json<DocumentSummary>,
    );
  },
};
