import { useState } from "react";
import { EMPTY_CREDENTIALS, isConfigured } from "../lib/providers";
import type { Credentials, ProviderCatalogue } from "../lib/providers";

type Props = {
  catalogue: ProviderCatalogue | null;
  credentials: Credentials;
  onChange: (next: Credentials) => void;
};

/**
 * Demo mode is the default and needs no interaction — a visitor can ask a
 * question on arrival. This panel is the opt-in path for anyone who wants to
 * run their own lease through their own account, which is also the only way to
 * avoid the shared demo's rate limit.
 */
export function ProviderPanel({ catalogue, credentials, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const configured = isConfigured(credentials);
  const set = (patch: Partial<Credentials>) => onChange({ ...credentials, ...patch });

  const llm = catalogue?.llm ?? [];
  const embedding = catalogue?.embedding ?? [];
  const activeLlm = llm.find((p) => p.id === credentials.llmProvider);
  const activeEmbedding = embedding.find((p) => p.id === credentials.embeddingProvider);

  return (
    <div className={`provider-panel ${configured ? "byok" : ""}`}>
      <button className="provider-toggle" onClick={() => setOpen((v) => !v)}>
        <span className={`dot ${configured ? "dot-byok" : "dot-demo"}`} />
        {configured ? (
          <>
            Using your <strong>{activeLlm?.label ?? credentials.llmProvider}</strong> key
          </>
        ) : catalogue?.demo_available ? (
          <>Demo mode — no key needed</>
        ) : (
          <>Offline mode — add a key for real answers</>
        )}
        <span className="chevron">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="provider-body">
          <p className="small muted">
            Bring your own key and your lease is processed under your account, not
            this site&apos;s. The key is held in memory for this tab only — never
            stored, never logged, never saved to the database. It is sent to this
            server on each request, because retrieval runs here; if you&apos;d rather
            it never left your machine, run FinePrint locally instead.
          </p>

          <div className="provider-grid">
            <label>
              Answering model
              <select
                value={credentials.llmProvider}
                onChange={(e) => set({ llmProvider: e.target.value, smartModel: "", cheapModel: "" })}
              >
                {llm.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              API key
              <input
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder={credentials.llmProvider === "anthropic" ? "sk-ant-…" : "sk-…"}
                value={credentials.llmKey}
                onChange={(e) => set({ llmKey: e.target.value.trim() })}
              />
            </label>
            <label>
              Model
              <input
                placeholder={activeLlm?.default_smart ?? "provider default"}
                value={credentials.smartModel}
                onChange={(e) => set({ smartModel: e.target.value.trim() })}
              />
            </label>
          </div>

          <div className="provider-grid">
            <label>
              Embeddings
              <select
                value={credentials.embeddingProvider}
                onChange={(e) => set({ embeddingProvider: e.target.value, embeddingModel: "" })}
              >
                {embedding.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              API key
              <input
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder="separate from the answering key"
                value={credentials.embeddingKey}
                onChange={(e) => set({ embeddingKey: e.target.value.trim() })}
              />
            </label>
            <label>
              Model
              <input
                placeholder={activeEmbedding?.default_model ?? "provider default"}
                value={credentials.embeddingModel}
                onChange={(e) => set({ embeddingModel: e.target.value.trim() })}
              />
            </label>
          </div>

          {/* Anthropic has no embeddings endpoint, so this pairing is the
              normal case rather than a mistake — say so before it looks like one. */}
          {credentials.llmKey && !credentials.embeddingKey && (
            <p className="small note">
              Without an embeddings key, search falls back to keyword matching —
              answers stay grounded, but questions phrased differently from your
              lease&apos;s wording may miss.
            </p>
          )}

          <p className="small note">
            Upload a lease and its addenda with the <em>same</em> embeddings
            provider. Vectors from different models can&apos;t be compared, so
            mixing them is refused rather than silently ranked by noise.
          </p>

          {configured && (
            <button className="link-button" onClick={() => onChange({ ...EMPTY_CREDENTIALS })}>
              Clear keys and return to demo mode
            </button>
          )}
        </div>
      )}
    </div>
  );
}
