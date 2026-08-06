import type { Answer, Citation, Clause } from "../lib/api";

type Props = {
  answer: Answer;
  onCite: (clause: Clause) => void;
};

export function AnswerView({ answer, onCite }: Props) {
  if (answer.status !== "answered") {
    return <NotCoveredCard answer={answer} onCite={onCite} />;
  }
  return (
    <div className="answer">
      <p className="answer-text">
        <CitedText text={answer.answer} citations={answer.citations} onCite={onCite} />
      </p>
      <div className="citation-row">
        {answer.citations.map((c) => (
          <CitationChip key={c.clause.id} citation={c} onCite={onCite} />
        ))}
      </div>
      <Provenance answer={answer} />
    </div>
  );
}

/**
 * "Your lease doesn't address this" is a real answer with its own component,
 * not an error state. Half of real tenant questions aren't covered, and a
 * refusal styled like a failure teaches people to distrust the correct output.
 * It carries what the lease *does* say nearby, which is what makes it useful.
 */
function NotCoveredCard({ answer, onCite }: Props) {
  return (
    <div className="answer not-covered">
      <div className="not-covered-head">
        <span className="not-covered-icon" aria-hidden>
          —
        </span>
        <div>
          <strong>Your lease doesn&apos;t address this.</strong>
          {answer.nearest_topic && (
            <p className="muted">
              The closest thing it covers is <em>{answer.nearest_topic}</em>.
            </p>
          )}
        </div>
      </div>

      {answer.downgraded && (
        // Distinguishing "the lease is silent" from "we drafted something we
        // couldn't verify" matters: the second means the answer might exist and
        // we failed to stand it up, which is a different next step for the user.
        <p className="downgrade-note">
          We drafted an answer but couldn&apos;t verify it against your lease, so
          we&apos;re not showing it. {answer.downgrade_reason}
        </p>
      )}

      {answer.citations.length > 0 && (
        <>
          <p className="muted small">Clauses that came closest:</p>
          <div className="citation-row">
            {answer.citations.slice(0, 4).map((c) => (
              <CitationChip key={c.clause.id} citation={c} onCite={onCite} />
            ))}
          </div>
        </>
      )}
      <Provenance answer={answer} />
    </div>
  );
}

/** Turns inline [14(b)] markers in the answer text into clickable chips. */
function CitedText({
  text,
  citations,
  onCite,
}: {
  text: string;
  citations: Citation[];
  onCite: (clause: Clause) => void;
}) {
  const byNumber = new Map(citations.map((c) => [c.clause.number, c]));
  const parts = text.split(/(\[[^\]]+\])/g);

  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[([^\]]+)\]$/);
        const citation = match ? byNumber.get(match[1]) : undefined;
        if (!citation) return <span key={i}>{part}</span>;
        return (
          <button
            key={i}
            className="inline-cite"
            onClick={() => onCite(citation.clause)}
            title={citation.clause.heading || citation.clause.text.slice(0, 80)}
          >
            {citation.clause.number}
          </button>
        );
      })}
    </>
  );
}

function CitationChip({
  citation,
  onCite,
}: {
  citation: Citation;
  onCite: (clause: Clause) => void;
}) {
  const { clause, supersedes } = citation;
  return (
    <button className="chip" onClick={() => onCite(clause)}>
      <span className="chip-number">{clause.number}</span>
      <span className="chip-heading">
        {clause.heading || clause.text.slice(0, 40) + "…"}
      </span>
      {supersedes && (
        // The whole point of keeping both clauses through retrieval: the tenant
        // sees that the term changed, not just what it changed to.
        <span className="chip-amended" title={citation.superseded_reason}>
          amends {supersedes.number}
        </span>
      )}
    </button>
  );
}

function Provenance({ answer }: { answer: Answer }) {
  const failed = answer.verdicts.filter((v) => v.verdict !== "yes");
  return (
    <details className="provenance">
      <summary>
        {answer.latency_ms} ms
        {answer.verdicts.length > 0 && ` · ${answer.verdicts.length} claims checked`}
        {failed.length > 0 && ` · ${failed.length} flagged`}
      </summary>
      <ul>
        {answer.verdicts.map((v, i) => (
          <li key={i} className={`verdict verdict-${v.verdict}`}>
            <span className="verdict-mark">
              {v.verdict === "yes" ? "✓" : v.verdict === "partial" ? "~" : "✗"}
            </span>
            <span>
              {v.claim}
              <em className="muted"> — {v.reason}</em>
            </span>
          </li>
        ))}
      </ul>
      {answer.trace_id && <p className="muted small">trace {answer.trace_id}</p>}
    </details>
  );
}
