// Provider selection lives in memory for the lifetime of the tab and is sent
// as headers on each request. It is deliberately never written to
// localStorage: a key in localStorage survives the tab, is readable by any
// script that ends up on the page, and turns "I tried a demo" into "I left a
// credential on someone's website".

export type ProviderCatalogue = {
  llm: { id: string; label: string; default_smart: string; default_cheap: string }[];
  embedding: { id: string; label: string; default_model: string }[];
  demo_available: boolean;
  demo_llm_provider: string;
  demo_embedding_provider: string;
};

export type Credentials = {
  llmProvider: string;
  llmKey: string;
  smartModel: string;
  cheapModel: string;
  embeddingProvider: string;
  embeddingKey: string;
  embeddingModel: string;
};

export const EMPTY_CREDENTIALS: Credentials = {
  llmProvider: "anthropic",
  llmKey: "",
  smartModel: "",
  cheapModel: "",
  embeddingProvider: "voyage",
  embeddingKey: "",
  embeddingModel: "",
};

/** True once the user has supplied anything we can actually use. */
export function isConfigured(c: Credentials): boolean {
  return Boolean(c.llmKey || c.embeddingKey);
}

export function providerHeaders(c: Credentials | null): Record<string, string> {
  if (!c || !isConfigured(c)) return {};
  const headers: Record<string, string> = {};
  if (c.llmKey) {
    headers["x-llm-provider"] = c.llmProvider;
    headers["x-llm-key"] = c.llmKey;
    if (c.smartModel) headers["x-llm-smart-model"] = c.smartModel;
    if (c.cheapModel) headers["x-llm-cheap-model"] = c.cheapModel;
  }
  if (c.embeddingKey) {
    headers["x-embedding-provider"] = c.embeddingProvider;
    headers["x-embedding-key"] = c.embeddingKey;
    if (c.embeddingModel) headers["x-embedding-model"] = c.embeddingModel;
  }
  return headers;
}
