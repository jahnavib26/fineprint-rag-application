import { useCallback, useEffect, useState } from "react";
import { AnswerView } from "./components/AnswerView";
import { DocumentPane } from "./components/DocumentPane";
import { ProviderPanel } from "./components/ProviderPanel";
import { UploadPanel } from "./components/UploadPanel";
import { api, setCredentials } from "./lib/api";
import { EMPTY_CREDENTIALS } from "./lib/providers";
import type { Credentials, ProviderCatalogue } from "./lib/providers";
import type { Answer, Clause, DocumentSummary, DocumentText } from "./lib/api";

type Turn = { question: string; answer: Answer | null; error?: string };

const DEFAULT_LEASE = "maple-court";

export default function App() {
  const [leaseId, setLeaseId] = useState(DEFAULT_LEASE);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null);
  const [documentText, setDocumentText] = useState<DocumentText | null>(null);
  const [loadingDoc, setLoadingDoc] = useState(false);
  const [highlight, setHighlight] = useState<Clause | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [catalogue, setCatalogue] = useState<ProviderCatalogue | null>(null);
  const [credentials, setCreds] = useState<Credentials>(EMPTY_CREDENTIALS);

  useEffect(() => {
    api.providers().then(setCatalogue).catch(() => setCatalogue(null));
  }, []);

  // The api module reads this on every request, so a key change takes effect
  // immediately without threading it through each call site.
  const updateCredentials = (next: Credentials) => {
    setCreds(next);
    setCredentials(next);
  };

  const refreshDocuments = useCallback(async () => {
    const docs = await api.documents(leaseId).catch(() => []);
    setDocuments(docs);
    setActiveDocumentId((current) =>
      current && docs.some((d) => d.id === current) ? current : (docs[0]?.id ?? null),
    );
  }, [leaseId]);

  useEffect(() => {
    setTurns([]);
    setHighlight(null);
    refreshDocuments();
  }, [refreshDocuments]);

  useEffect(() => {
    if (!activeDocumentId) {
      setDocumentText(null);
      return;
    }
    // Two citation clicks in quick succession — common when comparing an
    // original clause against the addendum that amended it — can have their
    // fetches resolve out of order, leaving one document's text on screen
    // under another document's highlight. Ignore anything but the latest.
    let current = true;
    setLoadingDoc(true);
    api
      .documentText(activeDocumentId)
      .then((text) => current && setDocumentText(text))
      .catch(() => current && setDocumentText(null))
      .finally(() => current && setLoadingDoc(false));
    return () => {
      current = false;
    };
  }, [activeDocumentId]);

  /**
   * A citation click has to switch the document pane first when the clause
   * lives in an addendum — which is exactly the case for every amended answer,
   * so it is the common path rather than an edge case.
   */
  const showClause = (clause: Clause) => {
    setActiveDocumentId(clause.document_id);
    setHighlight(clause);
  };

  const ask = async (event: React.FormEvent) => {
    event.preventDefault();
    const asked = question.trim();
    if (!asked || asking) return;

    setQuestion("");
    setAsking(true);
    setTurns((t) => [...t, { question: asked, answer: null }]);
    try {
      const answer = await api.ask(leaseId, asked);
      setTurns((t) =>
        t.map((turn, i) => (i === t.length - 1 ? { ...turn, answer } : turn)),
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setTurns((t) =>
        t.map((turn, i) => (i === t.length - 1 ? { ...turn, error: message } : turn)),
      );
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="app">
      <header className="topbar">
        <h1>
          Fine<span>Print</span>
        </h1>
        <p className="tagline">Ask your lease the questions you never read it for.</p>
        <div className="topbar-right">
          <input
            className="lease-input"
            value={leaseId}
            onChange={(e) => setLeaseId(e.target.value)}
            aria-label="Lease id"
          />
          <ProviderPanel
            catalogue={catalogue}
            credentials={credentials}
            onChange={updateCredentials}
          />
        </div>
      </header>

      <main className="panes">
        <section className="pane chat-pane">
          <header className="pane-header">
            <h2>Questions</h2>
          </header>

          <div className="chat-body">
            {turns.length === 0 && (
              <div className="empty">
                <p>Try asking:</p>
                <ul>
                  <li>Can I have a cat?</li>
                  <li>How much is my security deposit?</li>
                  <li>Can I list my apartment on Airbnb for a weekend?</li>
                  <li>Does my landlord pay my electric bill?</li>
                </ul>
              </div>
            )}

            {turns.map((turn, i) => (
              <div key={i} className="turn">
                <p className="question">{turn.question}</p>
                {turn.error && <p className="error">{turn.error}</p>}
                {!turn.answer && !turn.error && <p className="muted">Reading your lease…</p>}
                {turn.answer && <AnswerView answer={turn.answer} onCite={showClause} />}
              </div>
            ))}
          </div>

          <form className="ask" onSubmit={ask}>
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about your lease…"
              aria-label="Question"
            />
            <button type="submit" disabled={asking || !question.trim()}>
              Ask
            </button>
          </form>

          <UploadPanel leaseId={leaseId} onUploaded={refreshDocuments} />
        </section>

        <DocumentPane
          documents={documents}
          activeDocumentId={activeDocumentId}
          text={documentText}
          highlight={highlight}
          loading={loadingDoc}
          onSelect={(id) => {
            setActiveDocumentId(id);
            setHighlight(null);
          }}
        />
      </main>
    </div>
  );
}
