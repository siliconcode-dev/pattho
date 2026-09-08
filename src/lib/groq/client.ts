import Groq from "groq-sdk";

interface KeyState {
  key: string;
  client: Groq;
  healthyUntilFailure: boolean;
  cooldownUntil: number;
}

const COOLDOWN_MS = 30_000;

function loadKeys(): string[] {
  const keys = Object.entries(process.env)
    .filter(([name]) => /^GROQ_API_KEY(_\d+)?$/.test(name))
    .map(([, value]) => value)
    .filter((value): value is string => Boolean(value));

  if (keys.length === 0) {
    throw new Error(
      "No Groq API keys found. Set GROQ_API_KEY / GROQ_API_KEY_2 / ... in .env.local",
    );
  }

  return keys;
}

let pool: KeyState[] | null = null;
let cursor = 0;

function getPool(): KeyState[] {
  if (!pool) {
    pool = loadKeys().map((key) => ({
      key,
      client: new Groq({ apiKey: key }),
      healthyUntilFailure: true,
      cooldownUntil: 0,
    }));
  }
  return pool;
}

function nextCandidate(states: KeyState[]): KeyState | null {
  const now = Date.now();
  for (let i = 0; i < states.length; i++) {
    const state = states[(cursor + i) % states.length];
    if (state.cooldownUntil <= now) {
      cursor = (cursor + i + 1) % states.length;
      return state;
    }
  }
  return null;
}

function isRetryableError(error: unknown): boolean {
  const status = (error as { status?: number })?.status;
  if (status === undefined) return true; // network errors carry no status — treat as retryable
  // 400 is a malformed request (bad model/prompt) — a different key won't fix it.
  // Everything else (401/403 bad-or-revoked key, 404, 429 rate limit, 5xx) is
  // per-key or transient, so the rotation pool should route around it.
  return status !== 400;
}

export interface GroqChatOptions {
  model: string;
  messages: Groq.Chat.Completions.ChatCompletionMessageParam[];
  reasoningEffort?: "low" | "medium" | "high";
  stream?: boolean;
}

/**
 * Sends a chat completion through the rotating Groq key pool. On a
 * retryable failure (429/5xx/network), the failing key is put on a
 * cooldown and the next healthy key is tried before giving up.
 */
export async function groqChat(
  options: GroqChatOptions,
): Promise<Groq.Chat.Completions.ChatCompletion> {
  const states = getPool();
  let lastError: unknown;

  for (let attempt = 0; attempt < states.length; attempt++) {
    const state = nextCandidate(states);
    if (!state) break; // every key is cooling down

    try {
      return (await state.client.chat.completions.create({
        model: options.model,
        messages: options.messages,
        reasoning_effort: options.reasoningEffort,
        stream: false,
      })) as Groq.Chat.Completions.ChatCompletion;
    } catch (error) {
      lastError = error;
      if (!isRetryableError(error)) throw error;
      state.cooldownUntil = Date.now() + COOLDOWN_MS;
    }
  }

  throw new Error(
    `All Groq API keys exhausted or on cooldown. Last error: ${String(lastError)}`,
  );
}

/**
 * Streaming variant — same rotation/fallback behavior, but only up to
 * the point a stream successfully opens (a mid-stream failure is not
 * retried, since partial output may already be flushed to the client).
 */
export async function groqChatStream(
  options: GroqChatOptions,
): Promise<AsyncIterable<Groq.Chat.Completions.ChatCompletionChunk>> {
  const states = getPool();
  let lastError: unknown;

  for (let attempt = 0; attempt < states.length; attempt++) {
    const state = nextCandidate(states);
    if (!state) break;

    try {
      return await state.client.chat.completions.create({
        model: options.model,
        messages: options.messages,
        reasoning_effort: options.reasoningEffort,
        stream: true,
      });
    } catch (error) {
      lastError = error;
      if (!isRetryableError(error)) throw error;
      state.cooldownUntil = Date.now() + COOLDOWN_MS;
    }
  }

  throw new Error(
    `All Groq API keys exhausted or on cooldown. Last error: ${String(lastError)}`,
  );
}
