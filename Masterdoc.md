# Pattho AI (পাঠ্য AI) — Masterdoc

**One-line pitch:** A curriculum-tuned AI study tutor for Bangladeshi HSC students — built on RAG over the actual textbooks students study from (not generic global knowledge), running on Groq's GPT-OSS models, tuned to feel as sharp and polished as Claude/ChatGPT while staying strictly faithful to the curriculum.

**Core differentiator:** Generic AI (ChatGPT/Claude) answers from global knowledge, which may not match what a specific writer's book says or how a Bangladeshi board exam expects it answered. Pattho AI ingests every writer's book for a subject, chunks and embeds them, and answers from that grounded content — citing which writer/book/chapter it's drawing from.

---

## 1. Vision & Scope

- **Goal:** raise HSC board exam scores AND build real conceptual understanding — both weighted equally. Not an exam-drilling-only tool, not a pure Socratic tutor.
- **Launch curriculum:** Bangladeshi NCTB HSC (Class 11–12), **Science group first**. Commerce and Arts groups are the confirmed next expansion after Science ships.
- **Distribution model:** **B2C only for now** (direct-to-student). B2B (coaching centers/schools) is explicitly on hold — do not build institutional features (dashboards, seat licensing) until this changes.
- **Devices/connectivity:** mixed reality — Android phones with patchy data, plus shared computers. Build as a **PWA**, tolerant of low/hybrid bandwidth.
- **Language:** must handle **Bangla, English, and Banglish** (code-switched mixed input) — all three, not just one.

## 2. Curriculum & Content Reality

- **No single official "board book" at HSC level.** Unlike SSC, HSC subjects are taught from books written by **multiple different authors/publishers**, all covering the same NCTB curriculum. All of these need to be ingested — not just one canonical text.
- Currently sourced: multiple writers' PDFs for **Physics 1st Paper and 2nd Paper** only. Every other subject still needs sourcing — treat this as the pilot content set.
- **Full syllabus, not short syllabus.** This HSC cycle runs the full book, full marks, full duration — teach the complete textbook content, not a trimmed subset.
- **Past HSC board exam questions** should also be ingested into the RAG, so the AI can reference real board question patterns and difficulty.
- Real HSC exam structure to design practice/assessment features around: each written paper = **70 marks Creative Question (CQ)** (7 questions, student answers a subset, 10 marks each) + **30 marks MCQ**, one continuous 3-hour sitting, **no negative marking**. Science practical-heavy subjects split as 75 theory marks (25 MCQ + 50 CQ) + 25 practical marks — **practical/lab content is explicitly out of scope** for this product.

## 3. Content Pipeline (OCR & Ingestion)

- OCR runs on a **Google Cloud VM (4 CPU, 12GB RAM)** — spun up only for OCR + embedding generation, then **spun down** afterward. Not always-on. Same boot-up/spin-down pattern applies every time new books are added later.
- OCR output accuracy target: as high as possible (99.9% aspiration) for text, diagrams, chemical structures, and math formulas — acceptable to be compute-heavy since it's VM-bound, not laptop-bound.
- **Reality check to build around:** raw OCR on Bangla script realistically will not hit 99.9% — even strong general OCR tools show a meaningfully higher error rate on Bangla than Latin scripts, before factoring in math/diagrams. The accepted mitigation is **OCR + LLM-based cleanup/verification pass** (no human QA pass required — AI-only cleanup is acceptable).
- **Chunking:** built around each book's natural structure (chapter → topic → sub-topic → worked example), not fixed-size sliding windows.
- **Per-chunk metadata schema required:** writer/book, subject, paper (1st/2nd), chapter, content-type (textbook vs. board-question). This enables filtered retrieval.
- **Multi-writer conflict handling:** when writers differ on the same topic, the AI should give a **blended/synthesized answer while citing which writer's approach** it's drawing from — not force a single-writer-only mode, and not silently pick one writer.
- **Content maintenance:** hybrid — a mix of manual re-feeding and a built, repeatable re-ingestion pipeline. Whether the ingestion tool itself is a CLI script or a full admin dashboard is an **open item** (see §12).
- User-uploaded content (student homework photos/PDFs, see §5) should reuse this same OCR pipeline to extract text before feeding into the answer pipeline — see the vision-model note in §4.

## 4. AI / Model Layer

- **Provider:** Groq, using **GPT-OSS** models exclusively (no Claude in the loop). Groq's public web-search built-in tool exists for the fallback case below (billed per-request, not free, but cheap at low volume).
- **Two user-selectable modes:**
  - **"Flash"** = `openai/gpt-oss-20b` (faster, cheaper, higher usage limit)
  - **"Complex"** = `openai/gpt-oss-120b` (slower, higher quality, lower usage limit, costs more)
  - Both are available to every user; the split is a **usage/cost gate, not a feature gate** (see §9 for the pricing tie-in).
- **Reasoning effort:** adaptive per question complexity (Groq's `reasoning_effort`: low/medium/high), not fixed.
- **Visible answers should show worked reasoning steps** (the tutor "shows its work"), not just a final answer.
- **Do not prompt these models with explicit chain-of-thought instructions** ("think step by step") — GPT-OSS models reason internally, and OpenAI's own guidance says explicit CoT prompting can hurt quality on reasoning models. Use `reasoning_effort` as the tuning knob instead.
- **Server-side code execution** should be wired in for numerical subjects (Physics, Math, Chemistry) to verify calculations rather than trusting the model's native arithmetic.
- **"Claude-style" quality** is defined as a hybrid of tone (patient, encouraging, not robotic), depth (full multi-step breakdowns), and format (structured but natural) — this is the single most important thing to get right in the system prompt, and should be treated as an iterative tuning target during build, not a one-shot decision.
- **RAG-weak fallback (tiered):** 1) strong RAG match → answer with citation. 2) weak/no RAG match → try a live web search fallback, clearly cited as web-sourced (not curriculum-sourced). 3) if that also fails → fall back to the model's general knowledge, **clearly labeled as not curriculum-verified**.
- **In-session conversational memory is required** (e.g., "explain that differently" referencing the prior turn in the same session).
- **No vision model in the stack.** Groq deprecated its vision-capable Llama 4 Scout (June 2026); GPT-OSS 120B/20B are text-only. For the file/image upload feature (§5), route uploads through the OCR pipeline (§3) to extract text, then feed that text into the normal GPT-OSS pipeline — do not add a separate paid vision model (Qwen 3.6/3.8 27B) unless this decision is revisited.
- **Groq multi-region API key rotation (real operational constraint):** the current Groq account is a "pre-access" account issuing 10–12 regional API keys that share one rate limit but can go down independently per region. Build **rotation/fallback logic in the application layer** across all provided keys — this is not optional, it's a live reliability issue, not a hypothetical one.
- **Request queueing:** build a queue for v1 so students see a "please wait" state instead of raw errors when Groq's free-tier rate limits (~30 req/min, ~1,000 req/day) are hit under concurrent load.

## 5. Product UX & Interaction

- **Visual/interaction reference: Claude.ai's own chat interface** (a screenshot was provided as the direct reference). Replicate the shape, not the branding:
  - Welcoming header greeting the student by name
  - Single central input box
  - Sidebar listing past chat/session history
  - A model/mode selector (Flash/Complex)
  - A row of quick-action shortcut buttons (in Claude.ai's case: Write/Learn/Code/Life stuff/From Drive — adapt to this product's actual quick actions)
- **No third "Exam Coach" mode for v1** — just Flash/Complex.
- **Token-by-token streaming** responses required (not wait-then-reveal).
- **Input:** text **and file upload** (images, PDFs, docs) for v1 — students uploading their own homework/question photos is in scope.
- **Citations expand ("Source Reader" pattern):** tapping a citation should show the actual textbook page/paragraph an answer draws from — not just a text label.
- **No defined session structure.** Freeform chatbot style like Claude/ChatGPT — a new session starts whenever the user ends the previous one. No "pick a chapter, start/end a study session" wrapper.

## 6. Personalization & Gamification

- **No parent/teacher dashboard for v1** — everything is student-facing only (consistent with the B2C-only decision in §1).
- **Per-topic mastery score** should be built for v1, tracking weak chapters/sub-topics from a student's questions and quiz answers.
- **Revisiting weak topics stays student-initiated for v1** — no proactive spaced-repetition nudges/notifications yet (that's a natural v2 addition).
- **Answer style is a hybrid:** mix direct answers with some Socratic/attempt-first prompting rather than always just answering. This is a deliberate trade-off against pure "impress in seconds" helpfulness, made consciously to avoid pure cognitive-offloading.
- **Gamification (streaks, points, leaderboards) is IN for v1**, not deferred.
- **Student profile is unified across all subjects** (not siloed per subject) — one profile per student, with per-subject mastery breakdown nested inside. (This was Claude's recommendation, adopted by the founder when asked to pick.)
- **Writer preference is a persistent memory:** once a student shows/states a preference for a particular writer's explanation style, remember it and default to it automatically in future sessions.

## 7. Practice & Assessment

- **Practice question format is hybrid** — freeform quiz-style if the student doesn't specify, or exact HSC CQ (10-mark, answer-a-subset) + MCQ format if the student asks for board-style practice.
- **No negative marking on practice MCQs** — matches the real HSC exam.
- **The AI should actually grade written CQ-style answers** against a marking-scheme-like rubric (structure, keywords, completeness) — not just check short/numerical answers.
- **Practical/lab content (Science's 25-mark practical component) is out of scope** — a chatbot can't meaningfully substitute for it.
- **Practice questions = a mix** of real ingested board questions and freshly AI-generated ones.
- **Timed practice mode (simulating exam time pressure) is deferred to v2/v3** — untimed practice only for v1.
- **After a practice session, give a full breakdown** (specific topics/mistakes to review, tied into the mastery tracking in §6) — not just a raw score.

## 8. Content Safety & Academic Integrity

- **Model-answer restraint is a hybrid, not fully resolved:** the AI should distinguish between clearly-labeled exam-practice contexts (where a full model CQ answer is fine and expected) and generic "write my homework" requests (where it should lean toward guided help rather than a complete submittable essay). **The exact rule/trigger for this distinction is an open item to refine during build** (see §12).
- **No built-in content moderation to keep conversations strictly on-topic** — considered unnecessary for this product.
- **Minor/guardian consent for B2B accounts** would sit with the coaching center/school (not applicable now, since B2B is on hold) — **no explicit consent gate was specified for direct B2C signups** beyond the general privacy consent step in §10.
- **The AI should flag its own uncertainty** (e.g., "this may need verification with your teacher") when confidence is low — do not have it answer with false confidence.
- **Book-fidelity rule:** if a writer's book is factually outdated or wrong on some point, the AI **stays faithful to what the book says** (because board exams grade against the book), but should also **cite the current real-world standard separately** — e.g., "the book says X, but current real-world standards are Y — follow your book for exam purposes." Never silently override the book.
- **Standard AI safety handling is sufficient** for Bangladesh-specific sensitive content (political content in Civics/History, religious content in humanities) — no special local content tuning was requested.

## 9. Business Model & Monetization

- **B2C only, freemium model.**
- **Flash and Complex/Pro are both available to every user**, gated by **usage limits, not features**: Flash = higher daily usage limit at lower cost; Complex/Pro = lower usage limit at higher cost. This usage/cost gate is also the free/paid boundary.
- **Kickoff phase is entirely free** — no paid tier is actually active at launch. Monetization activates later; exact trigger point (user count, date) is undecided and deferred.
- **Payments: start with simple manual payment collection.** Do not build automated bKash/Nagad/Rocket integration for v1 — that's a later addition once monetization actually turns on. (Context: bKash/Nagad/Rocket are the dominant payment rails in Bangladesh and should be the eventual target, just not at v1.)
- **No formal free trial** — instead, an always-free lower tier sits permanently alongside the paid tier.
- **No B2B pricing needed right now** (per-student/per-seat licensing was the tentative model if/when B2B resumes — keep this in mind for the architecture, but do not build it now).
- **Pricing figure (BDT/month) is fully undecided** — to be validated with real users once monetization is switched on.

## 10. Tech Stack & Infrastructure

- **Frontend:** Next.js, deployed on **Vercel free tier**.
- **UI:** Shadcn components, **Anime.js v4** for animations/transitions.
- **Auth/relational data/storage:** Supabase (free tier) — used for auth, relational data, and file storage.
- **Vector database:** **Qdrant Cloud** (1GB free tier, no inactivity pause) — chosen over Supabase/pgvector specifically for the vector layer because it doesn't pause after inactivity, which matters given the intermittent GCP-VM-driven ingestion pattern.
- **Embedding model:** not yet locked, but **BGE-M3** is the recommended default — open-source, MIT-licensed (commercial-use safe), strong multilingual + hybrid dense/sparse retrieval, covers Bangla well. Confirm before Phase 1 of the build plan.
- **OCR/embedding compute:** Google Cloud VM (4 CPU, 12GB RAM), boot-up/spin-down only when ingesting content (see §3).
- **Backend language/framework:** delegated to Claude Code's judgment during build (no founder preference stated). Python is worth strong consideration given the RAG/embedding tooling ecosystem, but this is not mandated.
- **Groq API key management:** application-layer rotation across multiple regional keys is required (see §4) — not delegated to any external proxy/gateway.
- **Request queueing** for Groq rate-limit resilience is required for v1 (see §4).
- **Hosting is deliberately split:** app (frontend+backend) on Vercel free tier; heavy OCR/embedding compute on GCP VM (spun up only when needed) — this keeps GCP spend isolated to ingestion bursts only.

## 11. Privacy & Compliance

- **Bangladesh's Personal Data Protection Act, 2026 (PDPA) is real, in-force law** — consent-centric, covers children's data protection explicitly, requires breach notification and data-subject rights (access/correct/erase). Since a large share of HSC students are minors, this is directly relevant.
- **A formal privacy policy / consent step at signup is required for v1.**
- **Data residency:** PDPA requires certain "restricted"/critical data to have at least one real-time synced copy stored inside Bangladesh. The founder is **comfortable deferring this** for now and comfortable with curriculum/textbook content (non-personal) living outside Bangladesh on GCP. **This is a real compliance gap to revisit once there are actual paying/signed-up users** — flag it, don't silently forget it (see §12).
- **Signup data collected:** name, unique username, school/college name, class/group.
- **Social sign-in:** Google, Discord, and X (Twitter) for v1; Facebook sign-in to be added later.
- **Chat history is retained indefinitely** (supports the mastery-tracking feature in §6).
- **Full account settings page required for v1**, including account/data deletion — i.e., build a "right to be forgotten" path from the start, don't defer it.
- No B2B data-visibility question applies currently (B2B is on hold).

## 12. Open Items — Explicitly Deferred, Not Forgotten

These were consciously left open during discovery. Do not treat their absence from earlier sections as an oversight — surface them again at the relevant build phase rather than silently deciding for the founder:

1. **Ingestion pipeline interface** — CLI script the founder runs themselves, vs. a full admin web dashboard. Needs a decision before Phase 1 scales past the Physics pilot.
2. **Model-answer restraint rule** (§8) — the precise trigger distinguishing "exam practice, full model answer OK" from "generic homework help, nudge toward guided answer" needs to be nailed down concretely, likely as explicit system-prompt logic or a UI mode toggle.
3. **Bangladesh PDPA data residency** (§11) — deferred, but a real compliance item once the product has real signed-up users.
4. **Backend language/framework** — delegated to Claude Code.
5. **Groq scaling trigger** — no defined point (user count/date) at which the product moves off Groq's free tier to paid credits.
6. **Pricing figure** — no BDT/month number decided yet.
7. **Launch/growth channel** — no committed plan yet, though existing Bangladeshi HSC-prep Facebook groups are a strong candidate given they're already a proven behavior pattern for this exact audience.
8. **Timeline and success metrics for v1-alpha/v1-beta** — both explicitly open-ended; the founder already has real HSC Science students lined up and ready to test whenever the build reaches beta.

## 13. Roadmap Beyond v1

- v1: HSC Science group, Physics-first (since that's the only subject with sourced content today).
- Next: expand Science group to its other subjects (Chemistry, Biology, Higher Math, ICT, Bangla, English — whichever remain).
- After Science group is solid: **Commerce and Arts groups** (confirmed next expansion, not yet scoped in detail).
- No known direct Bangladesh competitor doing this exact curriculum-tuned-RAG approach — the founder believes this space is genuinely open right now.
