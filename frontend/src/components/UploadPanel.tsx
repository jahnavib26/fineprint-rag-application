import { useState } from "react";
import { api } from "../lib/api";

type Props = { leaseId: string; onUploaded: () => void };

export function UploadPanel({ leaseId, onUploaded }: Props) {
  const [kind, setKind] = useState("original");
  const [signedDate, setSignedDate] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const upload = async (file: File) => {
    setBusy(true);
    setStatus(null);
    try {
      const doc = await api.upload(leaseId, file, kind, signedDate);
      setStatus(
        doc.strategy === "fallback"
          ? `${doc.filename}: little clause structure detected — split into ${doc.clause_count} passages.`
          : `${doc.filename}: ${doc.clause_count} clauses.`,
      );
      onUploaded();
    } catch (error) {
      // A scanned PDF comes back 422 with an explanation. It isn't a crash and
      // shouldn't read like one — the user needs to know to re-export it.
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="upload">
      <summary>Add a document</summary>
      <div className="upload-body">
        <label>
          Type
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="original">Original lease</option>
            <option value="addendum">Addendum</option>
          </select>
        </label>
        <label>
          Signed
          {/* Ordering addenda by signature date is what decides which clause
              wins when two documents disagree. */}
          <input
            type="date"
            value={signedDate}
            onChange={(e) => setSignedDate(e.target.value)}
          />
        </label>
        <input
          type="file"
          accept="application/pdf"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload(file);
            e.target.value = "";
          }}
        />
        {busy && <p className="muted small">Reading the document…</p>}
        {status && <p className="small">{status}</p>}
      </div>
    </details>
  );
}
