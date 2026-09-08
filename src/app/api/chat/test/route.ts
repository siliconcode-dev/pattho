import { groqChatStream } from "@/lib/groq/client";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const { prompt } = (await request.json()) as { prompt?: string };

  if (!prompt || typeof prompt !== "string") {
    return new Response("Missing 'prompt' in request body", { status: 400 });
  }

  const groqStream = await groqChatStream({
    model: "openai/gpt-oss-20b",
    reasoningEffort: "low",
    messages: [{ role: "user", content: prompt }],
  });

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for await (const chunk of groqStream) {
          const text = chunk.choices[0]?.delta?.content ?? "";
          if (text) controller.enqueue(encoder.encode(text));
        }
      } catch (error) {
        controller.error(error);
        return;
      }
      controller.close();
    },
  });

  return new Response(stream, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
