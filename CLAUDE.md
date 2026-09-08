@AGENTS.md

# Claude.md — Pattho AI (পাঠ্য AI)

Project instructions for Claude Code. Read `Masterdoc.md` for full product context and rationale, and `Build_plan.md` for the phased build order — this file is the quick-reference/working-conventions layer, not a replacement for either.

## What this project is

A curriculum-tuned AI study tutor for Bangladeshi HSC (Class 11–12) students, Science group first, Physics-first within that. RAG over the actual textbooks (multiple writers per subject) + Groq's GPT-OSS models, tuned to feel like a sharp, polished tutor rather than a generic chatbot bolted onto some PDFs.

## Current build phase

Check `Build_plan.md` for the phase list — work through phases in order, checkpoint before moving on, and don't build ahead into a later phase's scope even if it looks quick.

## Non-negotiable constraints (do not silently deviate from these)

- **No Claude/Anthropic models in the answer pipeline.** This product's whole premise is Groq's GPT-OSS models tuned to feel Claude-quality — not actually calling Claude.
- **Text-only models (`openai/gpt-oss-20b`, `openai/gpt-oss-120b`).** No vision model. Images/PDFs go through OCR text-extraction, never direct image-to-model calls.
- **Book-fidelity rule:** when curriculum content conflicts with real-world accuracy, the AI stays faithful to the book (exams grade against the book) and separately notes the real-world standard — it never silently "corrects" the curriculum.
- **B2C only.** No institution/dashboard/seat-licensing features unless the founder explicitly reopens B2B.
- **No lab/practical-simulation content.** Explicitly out of scope.
- **Groq key rotation is mandatory infrastructure**, not a nice-to-have — the founder's current Groq account issues multiple regional keys that can go down independently. Every Groq call should go through the rotation/fallback layer, with a request queue backing it up under rate-limit pressure.
- **No explicit chain-of-thought prompting** ("think step by step") to GPT-OSS models — use the `reasoning_effort` parameter instead; these models already reason internally and CoT prompting can hurt output quality.

## Model naming (user-facing vs. API)

| User sees | API model | Notes |
|---|---|---|
| Flash | `openai/gpt-oss-20b` | Higher usage limit, lower cost |
| Complex (also "Pro" in pricing copy) | `openai/gpt-oss-120b` | Lower usage limit, higher cost |

Use `reasoning_effort: low/medium/high` adaptively on both, based on question complexity — never hardcode one level.

## Stack quick-reference

- Frontend: Next.js on Vercel (free tier)
- UI: Shadcn components (favor Magic UI's component set specifically), Anime.js v4 for animation
- Auth/relational/storage: Supabase
- Vector DB: Qdrant Cloud (free tier — chosen over Supabase/pgvector specifically to avoid the 7-day inactivity pause; **unconfirmed** — see Phase 0 flags, third-party sources suggest Qdrant free tier may also pause on inactivity, mitigated with a keep-alive cron)
- Embedding model: BGE-M3 (default recommendation — confirm before Phase 1 locks it in)
- OCR/embedding compute: GCP VM, 4 CPU/12GB RAM, boot-on-demand only — never leave it running idle
- Backend language/framework: Next.js API routes (TypeScript) for the live chat/RAG path; Python for the GCP VM OCR/embedding ingestion job (Phase 1) — decided at Phase 0 kickoff

## Content & data conventions

- Every ingested chunk needs metadata: `writer/book`, `subject`, `paper` (1st/2nd), `chapter`, `content-type` (`textbook` | `board-question`).
- Chunk by book structure (chapter → topic → sub-topic → worked example) — never fixed-size sliding windows.
- Every answer that draws on RAG content should carry a citation the UI can expand into the source ("Source Reader" pattern) — don't build answers that hide sourcing.
- When multiple writers disagree, blend the answer and name whose approach is being used — don't silently pick one writer or average them into something unattributed.

## Open items to flag back to the founder (don't decide these unilaterally)

See Masterdoc §12 for full context. In short: ingestion pipeline CLI-vs-dashboard, the exact model-answer-restraint trigger rule, Bangladesh PDPA data residency, Groq free-to-paid scaling trigger, final pricing figure, launch channel, and v1-alpha/beta timing/success metrics are all intentionally undecided. If a build decision depends on one of these, pick the most reasonable default from `Build_plan.md`'s guidance and flag it clearly in your output rather than guessing silently or blocking on it.

## Workflow conventions

- Run `/compact` after each completed phase. Never `/clear` — earlier phases' context matters for later ones (e.g., the metadata schema from Phase 1 is load-bearing for Phase 2 retrieval).
- Sandboxed bypass-permission mode, no command execution outside the workspace folder, git safety on. (2026-09-08: founder twice authorized a narrow SSH exception for the `ocr-patho-ai` ingestion VM. First attempt — GCE metadata SSH-key-to-new-user mechanism — never worked (silently corrupted the stored key). Second attempt — appending the key directly to the existing `siliconxcode` user's `~/.ssh/authorized_keys` via browser SSH — worked briefly, then access was lost again, most likely GCE's guest agent reconciling that file against instance metadata and stripping the manually-added entry. Reverted to the original rule until a persistent method is found; VM commands go through the founder pasting into the Console's browser SSH.)
- **Windows filesystem note:** this repo lives on a case-insensitive filesystem — `Claude.md` and `CLAUDE.md` are the same file here. Don't create a differently-cased duplicate expecting it to coexist.
