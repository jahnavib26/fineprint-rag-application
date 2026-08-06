import { useEffect, useRef } from "react";
import type { Clause, DocumentSummary, DocumentText } from "../lib/api";

type Props = {
  documents: DocumentSummary[];
  activeDocumentId: string | null;
  text: DocumentText | null;
  highlight: Clause | null;
  loading: boolean;
  onSelect: (documentId: string) => void;
};

/**
 * Renders the extracted text the offsets were computed against — not a PDF
 * canvas. Highlighting by character offset into that exact string is what makes
 * a citation click land on the right paragraph without any coordinate mapping,
 * and it's the reason ingestion stores full_text alongside the clauses.
 */
export function DocumentPane({
  documents,
  activeDocumentId,
  text,
  highlight,
  loading,
  onSelect,
}: Props) {
  const markRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    markRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [highlight?.id, text?.id]);

  return (
    <section className="pane document-pane">
      <header className="pane-header">
        <h2>Your documents</h2>
      </header>

      <div className="doc-tabs">
        {documents.map((doc) => (
          <button
            key={doc.id}
            className={`doc-tab ${doc.id === activeDocumentId ? "active" : ""}`}
            onClick={() => onSelect(doc.id)}
          >
            <span className={`kind kind-${doc.kind}`}>{doc.kind}</span>
            <span className="doc-name">{doc.filename}</span>
            <ConfidenceBadge document={doc} />
          </button>
        ))}
      </div>

      <div className="doc-body">
        {loading && <p className="muted">Loading…</p>}
        {!loading && !text && <p className="muted">Upload a lease to get started.</p>}
        {text && <Highlighted text={text.full_text} clause={highlight} markRef={markRef} />}
      </div>
    </section>
  );
}

/**
 * Surfaces how well the segmenter understood this document. A document that
 * fell back to fixed-size chunking answers questions less precisely, and the
 * tenant should be able to see that rather than wonder why citations look odd.
 */
function ConfidenceBadge({ document }: { document: DocumentSummary }) {
  const low = document.strategy === "fallback";
  return (
    <span
      className={`badge ${low ? "badge-warn" : "badge-ok"}`}
      title={
        low
          ? "This document has little detectable clause structure, so it was split " +
            "into overlapping chunks. Citations point at passages, not numbered clauses."
          : `Clause structure detected with ${Math.round(
              document.structure_confidence * 100,
            )}% confidence.`
      }
    >
      {low ? "low structure" : `${document.clause_count} clauses`}
    </span>
  );
}

function Highlighted({
  text,
  clause,
  markRef,
}: {
  text: string;
  clause: Clause | null;
  markRef: React.MutableRefObject<HTMLElement | null>;
}) {
  if (!clause) return <pre className="doc-text">{text}</pre>;

  // Clamp defensively: a stale highlight from a previously selected document
  // would otherwise slice at offsets this text doesn't have.
  const start = Math.max(0, Math.min(clause.char_start, text.length));
  const end = Math.max(start, Math.min(clause.char_end, text.length));

  return (
    <pre className="doc-text">
      {text.slice(0, start)}
      <mark ref={markRef} className="clause-highlight">
        {text.slice(start, end)}
      </mark>
      {text.slice(end)}
    </pre>
  );
}
