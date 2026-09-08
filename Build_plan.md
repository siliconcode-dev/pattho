# Pattho AI — Build Plan

Phased build plan for Claude Code. Build and validate one phase before moving to the next. Full context/rationale for every decision referenced here lives in `Masterdoc.md` — read that first. Run `/compact` after each completed phase (not `/clear`).

Pilot content scope for the whole plan: **HSC Science group, Physics 1st & 2nd Paper only**, multiple writers. Do not build for other subjects until Physics is working end-to-end — the architecture should generalize, but don't spend effort ingesting subjects that aren't sourced yet.

---

## Phase 0 — Foundations

**Goal:** empty-but-working scaffolding for every piece of the stack, before any real content or AI logic.

- Set up the Next.js repo, deploy a "hello world" to Vercel free tier.
- Set up Supabase project: auth (email + Google/Discord/X sign-in per Masterdoc §11), a `users` table with the signup fields (name, unique username, school/college, class/group), and storage bucket for uploaded files.
- Set up Qdrant Cloud free-tier collection (placeholder schema — refine once chunking is designed in Phase 1).
- Set up the GCP VM (4 CPU/12GB RAM) as a **stoppable** instance — confirm it can be started/stopped on demand, since it should never run idle.
- Set up Groq API access with the multi-region key set the founder has; build the **key rotation/fallback layer** now, at the foundation level, since every later phase depends on it. Test that a failed region correctly falls over to another key without the request failing outright.
- Decide and lock in the backend language/framework (delegated to you — pick based on best fit for the RAG/Groq pipeline work in Phase 1–2).
- **Checkpoint before moving on:** can you round-trip a trivial request through Next.js → backend → Groq (any model, no RAG yet) → streamed response back to the browser? Get that working before anything else.

## Phase 1 — Content Ingestion Pipeline

**Goal:** turn the Physics PDFs (multiple writers, both papers) into searchable, metadata-tagged vectors in LanceDB.

*(2026-09-08: migrated off Qdrant Cloud, set up in Phase 0 — its 4GB free-tier disk couldn't hold the full corpus once ColBERT's per-token multivectors were accounted for, and self-hosting a bigger Qdrant on an Oracle Always Free VM was blocked by regional ARM capacity shortage. LanceDB is an embedded library that writes straight to Backblaze B2 object storage — 10GB free forever, no card required, no server/capacity to run out of. See `ingestion/lancedb_store.py`.)*

- Build the OCR step to run on the GCP VM: input Physics PDFs, output cleaned text. Use OCR + an LLM-based cleanup pass (per Masterdoc §3 — no human QA step required, but log confidence/uncertainty per page so problems are traceable later).
- Confirm/lock the embedding model — **BGE-M3** is the recommended default (multilingual, MIT-licensed, hybrid dense/sparse). Swap if you find a clearly better fit during testing, but don't leave this undecided past this phase.
- Build **structure-aware chunking**: respect each book's chapter → topic → sub-topic → worked-example hierarchy. Don't fall back to fixed-size chunking even if it's more work.
- Implement the **per-chunk metadata schema**: writer/book, subject, paper, chapter, content-type (textbook vs. board-question).
- Source and ingest **past HSC board exam questions** for Physics alongside the textbook content, tagged with `content-type: board-question`.
- Build the ingestion pipeline as a **CLI script the founder runs manually for now** (fastest path to unblock later phases) — flag clearly in code/comments that an admin dashboard is an open item (Masterdoc §12) that may replace this later. Don't over-invest in the CLI's UX.
- Wire up the GCP VM boot-up → run pipeline → write to LanceDB (B2) → spin-down flow end-to-end.
- **Checkpoint:** query the LanceDB table directly (outside the app) for a known Physics topic and confirm the right chunks, from the right writers, with correct metadata, come back.

## Phase 2 — RAG + Answer Engine

**Goal:** a working backend that takes a student question and returns a grounded, cited, streamed answer.

- Build retrieval: query → embed → LanceDB search (dense + BM25 FTS, ColBERT rerank) → assemble context, respecting the metadata schema (e.g., filter by subject/paper when known).
- Implement the **Flash/Complex model split**: `openai/gpt-oss-20b` for Flash, `openai/gpt-oss-120b` for Complex, both user-selectable.
- Implement **adaptive `reasoning_effort`** (low/medium/high) based on question complexity — don't hardcode one level.
- Do **not** add explicit chain-of-thought prompting ("think step by step") — rely on `reasoning_effort` and let the model reason internally per Masterdoc §4.
- Design and iterate the **system prompt** for "Claude-style" tone/depth/format — treat this as an ongoing tuning loop, not a single draft. Test against real Physics questions from both papers.
- Implement the **multi-writer synthesis + attribution** behavior: when writers differ, blend the answer but cite whose approach is being used.
- Wire in **server-side code execution** for numerical Physics problems.
- Implement the **tiered fallback**: strong RAG match → cited answer; weak/no match → web search fallback (cited as web-sourced); total failure → general model knowledge (clearly labeled as not curriculum-verified).
- Implement the **uncertainty flag** ("this may need verification with your teacher") for low-confidence answers.
- Implement the **book-fidelity-with-citation rule**: stay faithful to the book, but separately note current real-world standards if they diverge (Masterdoc §8).
- Implement **in-session memory** (conversation context within one session).
- Build the **request queue** for Groq rate-limit resilience.
- Stream responses token-by-token from backend to frontend.
- **Checkpoint:** a real Physics question, asked in Bangla, English, and Banglish, each returns a correctly-cited, streamed, reasonably fast answer, with graceful behavior when you deliberately exhaust a region's rate limit (confirms the rotation/queue logic from Phase 0/2 actually works under stress).

## Phase 3 — Chat Frontend

**Goal:** the actual student-facing UI, modeled on the Claude.ai reference screenshot (Masterdoc §5).

- Build the core layout: welcoming header (greet by name), central input box, sidebar of past sessions, Flash/Complex mode selector, quick-action row (adapt the specific actions to this product rather than copying Claude.ai's literally).
- Implement streaming message rendering (buffer partial markdown correctly — don't let incomplete formatting break the layout).
- Implement file upload (images, PDFs, docs) — route uploads through the Phase 1 OCR pipeline to extract text, then feed that text into the Phase 2 answer engine. No separate vision model.
- Implement the **expandable "Source Reader" citation** — tapping a citation shows the actual textbook page/paragraph.
- Freeform session behavior: no forced start/end structure, new session whenever the student starts one.
- PWA setup: installable, tolerant of low/patchy bandwidth (graceful loading states, retry logic for flaky connections — don't assume steady connectivity).
- **Checkpoint:** a first-time student can land on the page, ask a real Physics question in whichever language mix they type, watch it stream in, and expand a citation to see the source — all without any account yet (auth comes in Phase 6, but decide now whether anonymous usage is even allowed pre-signup, since it wasn't explicitly settled in discovery — default to requiring signup unless you have a reason not to).

## Phase 4 — Personalization & Gamification

**Goal:** the system remembers and adapts to each student.

- Build the **unified student profile** (one profile per student, per-subject mastery nested inside — not siloed per-subject profiles).
- Build the **per-topic mastery score**, updated from questions asked and any quiz/practice results (Phase 5 feeds into this).
- Implement **writer-preference memory**: detect/ask for a preferred writer, store it, default to it automatically in future answers.
- Implement **gamification**: streaks, points, and leaderboards, scoped across the unified profile (not per-subject).
- Keep all revisiting/resurfacing of weak topics **student-initiated** — no proactive push notifications or nudges in v1.
- **Checkpoint:** ask the same student multiple questions across a session (and a second session), and confirm the mastery score and writer preference both persist and visibly affect behavior (e.g., defaulting to the remembered writer).

## Phase 5 — Practice & Assessment

**Goal:** generate and grade practice questions.

- Build hybrid practice-question generation: freeform quiz-style by default, or exact HSC CQ (10-mark, answer-a-subset) + MCQ format when the student asks for board-style practice.
- Pull from **both** the ingested real board-question bank and freshly AI-generated questions.
- No negative marking on practice MCQs.
- Build **CQ answer grading** against a marking-scheme-style rubric (structure, keywords, completeness) — this is a real grading feature, not a superficial check.
- Explicitly exclude any lab/practical-simulation content.
- Build the **post-practice breakdown** (topics/mistakes to review), feeding into the Phase 4 mastery score.
- Leave timed/exam-simulation mode out — that's v2/v3.
- Implement the **model-answer restraint rule** here concretely (this was an open item in Masterdoc §12): practice/exam-simulation context → full model CQ answers are fine; a student asking in a generic "write my homework" framing → nudge toward guided help instead of a complete submittable essay. Pick a concrete signal (e.g., an explicit "practice mode" UI toggle) rather than trying to infer intent from phrasing alone.
- **Checkpoint:** a student can request board-style Physics practice, get a properly-formatted CQ+MCQ set (mixing real and generated questions), submit written answers, get them graded against a rubric, and see a topic-level breakdown afterward.

## Phase 6 — Accounts, Privacy & Settings

**Goal:** real accounts with proper consent and data controls, ready for actual users.

- Finish Supabase auth: email + Google/Discord/X (Facebook later).
- Build the **privacy policy / consent step** at signup (Bangladesh PDPA children's-data provisions apply — don't skip this even in an early beta).
- Build the **full account settings page**, including account/data deletion.
- Confirm chat history retention is indefinite by default (no auto-expiry logic needed).
- **Do not** attempt Bangladesh data-residency compliance yet (Masterdoc §11/§12) — but leave a clear TODO/flag in the codebase so it isn't silently forgotten once the product has real signed-up users.
- **Checkpoint:** a new student can sign up (via any supported method), see and accept a real privacy notice, and later find and use account deletion.

## Phase 7 — Safety Pass & Internal Alpha

**Goal:** self-test the whole thing end-to-end before real students touch it.

- Run through Masterdoc §8 safety behaviors deliberately: ask for something that should trigger uncertainty-flagging, ask something where a writer's book might be outdated, ask a generic "write my essay" question vs. requesting practice-mode — confirm each behaves as designed.
- Load-test the Groq key rotation and request queue under simulated concurrent usage.
- No fixed timeline for this phase — the founder has explicitly left v1-alpha timing open-ended. Use that time to actually stress-test rather than rushing.

## Phase 8 — v1-Beta with Real Students

**Goal:** the founder already has real HSC Science students lined up and ready — get the product in front of them.

- No committed launch channel yet (existing Bangladeshi HSC-prep Facebook groups are a strong candidate per Masterdoc §13, but this is the founder's call to activate).
- No fixed success metric was set for this phase — treat it as genuinely open-ended feedback collection, not a pass/fail gate.
- Collect real usage against Groq's free-tier limits to inform the (currently undecided) scaling trigger.
- Feed real issues back into a fix/iterate loop before considering v1-stable.

---

## Explicit Non-Goals for v1 (do not build these unless the founder revisits them)

- B2B features of any kind (institution dashboards, seat licensing, per-institution billing)
- Parent/teacher dashboards
- Vision-model-based image understanding (use OCR text-extraction instead)
- Timed/exam-simulation practice mode
- Proactive spaced-repetition notifications
- Automated bKash/Nagad/Rocket payment integration
- Lab/practical-simulation content
- Bangladesh data-residency infrastructure
- Content moderation beyond standard AI safety handling
