"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { ShimmerButton } from "@/components/ui/shimmer-button";
import { BorderBeam } from "@/components/ui/border-beam";

export default function Home() {
  const [prompt, setPrompt] = useState("");
  const [answer, setAnswer] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAsk() {
    if (!prompt.trim() || streaming) return;
    setAnswer("");
    setError(null);
    setStreaming(true);

    try {
      const res = await fetch("/api/chat/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });

      if (!res.ok || !res.body) {
        throw new Error(await res.text());
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        setAnswer((prev) => prev + decoder.decode(value, { stream: true }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center bg-zinc-50 px-4 py-16 dark:bg-black">
      <main className="flex w-full max-w-2xl flex-col gap-6">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
            Pattho AI — Phase 0 checkpoint
          </h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            Groq round-trip test — no RAG, no auth, just streaming.
          </p>
        </div>

        <Card className="flex flex-col gap-4 p-4">
          <Textarea
            placeholder="Ask any Physics question..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
          />
          <ShimmerButton
            onClick={handleAsk}
            disabled={streaming || !prompt.trim()}
            className="self-end disabled:cursor-not-allowed disabled:opacity-50"
          >
            {streaming ? "Thinking..." : "Ask"}
          </ShimmerButton>
        </Card>

        {(answer || streaming || error) && (
          <Card className="relative min-h-32 overflow-hidden whitespace-pre-wrap p-4 text-sm text-zinc-800 dark:text-zinc-200">
            {error ? (
              <span className="text-red-500">{error}</span>
            ) : (
              answer || "…"
            )}
            {streaming && <BorderBeam duration={4} size={80} />}
          </Card>
        )}
      </main>
    </div>
  );
}
