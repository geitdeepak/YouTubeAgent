# Software Requirements Specification (SRS)

## EduTube Agent — Free AI Agent that Creates and Uploads AI-Education Videos to YouTube

| Field | Value |
|---|---|
| Document ID | EDT-SRS-001 |
| Version | 1.0 |
| Date | 2026-09-20 |
| Related docs | docs/LLR.md (EDT-LLR-001), docs/LLD.md (EDT-LLD-001), CLAUDE.md |
| Status | Baseline for implementation with Claude Code |

## 1. Introduction

### 1.1 Purpose

This document specifies the requirements for EduTube Agent, a local, zero-cost software system that
automatically researches a given topic from a queue, writes an educational script about Artificial
Intelligence (AI) concepts, produces narrated video with visuals and subtitles, generates YouTube
metadata and thumbnails, and uploads the result to a YouTube channel after an optional human
approval step.

The document is written so that an AI coding assistant (Claude Code in VS Code) can implement the
system without further clarification.

### 1.2 Scope

EduTube Agent **will**:

- Produce two video formats:
  - **Short** — YouTube Shorts, vertical 9:16, 30–40 seconds.
  - **Long** — standard video, horizontal 16:9, 4–5 minutes.
- Cover a single configurable **niche** (`content.niche` in config.yaml; default AI education, e.g. "What is a Transformer?", "RAG explained", "Overfitting vs Underfitting"). The relevance check (FR-04) filters topics against whatever niche is configured, and independently rejects unsafe content (sexual, graphic violence, hate speech, etc.) regardless of niche.
- Use only free / open-source components (local LLM via Ollama, edge-tts, Pexels free API, FFmpeg, Pillow, YouTube Data API free quota).
- Run on a single developer machine (Windows 10/11, Ubuntu 22.04+/WSL2, or macOS 13+).
- Be operated through a command-line interface (CLI) and optionally scheduled daily.

EduTube Agent **will not** (out of scope for v1.0):

- Generate AI video footage (text-to-video models) — paid/heavy.
- Clone real people's voices or use avatars / deepfakes.
- Manage comments, community posts, or analytics dashboards.
- Operate multiple YouTube channels simultaneously.

Note: v1.0 shipped CLI-only; a local web UI (§3.13) was added afterward to
cover topic submission, format selection, preview, approval and upload from
a browser, still running entirely on the operator's own machine.

### 1.3 Definitions & Acronyms

| Term | Meaning |
|---|---|
| Agent | The orchestrated pipeline where an LLM performs planning, writing and self-review steps and tools execute media tasks |
| LLM | Large Language Model; here a local model served by Ollama |
| TTS | Text-to-Speech; here edge-tts |
| Job | One end-to-end production run for one topic in one format |
| Stage | One step of a job (script, review, voice, visuals, render, metadata, upload) |
| Scene | A segment of a video with its own narration and visual |
| B-roll | Stock background footage from Pexels |
| Slide | A still image rendered by the system with Pillow (title, bullets, diagram, code) |
| Short | Vertical ≤ 40 s video published as a YouTube Short |
| Long | Horizontal 4–5 min video |
| Quota unit | YouTube Data API cost unit; default daily quota 10,000 |
| ASS | Advanced SubStation Alpha subtitle format (used to burn captions) |
| SRT | SubRip subtitle format (uploaded as a caption track / kept as sidecar) |

### 1.4 References

- YouTube Data API v3 — `videos.insert`, `thumbnails.set`, `captions.insert`
- Ollama REST/Python API and structured outputs (JSON schema in `format`)
- edge-tts Python package
- Pexels API v1 (videos search)
- FFmpeg documentation (libx264, concat demuxer, subtitles/ass filter, loudnorm)
- YouTube policies: Community Guidelines, altered/synthetic content disclosure, YPP "inauthentic (mass-produced/repetitive) content" policy

## 2. Overall Description

### 2.1 Product Perspective

A standalone Python 3.11+ application. External dependencies: EduTube Agent CLI orchestrates a Topic
Queue -> Orchestrator -> Stages pipeline producing `workspace/jobs/<id>/final.mp4`, driven by
`topics.csv` and `config.yaml`, and calling out to Ollama (local), edge-tts (MS online), Pexels API
(free key), YouTube Data API v3 (OAuth2), and FFmpeg/ffprobe (local binary).

### 2.2 Product Functions (summary)

1. Maintain a queue of AI-education topics with priority, format and optional source notes.
2. Generate a structured, scene-based script sized to the target duration.
3. Self-review the script for accuracy, clarity, and length; rewrite when below threshold.
4. Generate narration audio and word-level timings.
5. Generate subtitles (burned-in for all videos; SRT sidecar for Long).
6. Produce visuals: branded slides (title, bullets, definition, comparison, flow diagram, code) and Pexels b-roll.
7. Compose the final video with FFmpeg (scenes, captions, optional music, loudness normalization).
8. Generate SEO metadata (title, description, tags, hashtags, chapters) and a thumbnail (Long).
9. Hold the video for human approval (default) or auto-approve (configurable).
10. Upload to YouTube with resumable upload, set thumbnail, captions, privacy and AI disclosure.
11. Track job state in SQLite; resume failed jobs from the failed stage.
12. Run a daily batch via OS scheduler.

### 2.3 User Classes

| User | Description | Needs |
|---|---|---|
| Channel Owner / Creator (primary) | Educator who owns the YouTube channel | Add topics, review videos, approve uploads, tune style |
| Developer / Maintainer | Person running Claude Code, extending modules | Clear modules, tests, logs |

### 2.4 Operating Environment

- OS: Windows 10/11 (PowerShell), Ubuntu 22.04+/WSL2, macOS 13+.
- Python 3.11 or 3.12.
- FFmpeg ≥ 6.0 and ffprobe on PATH.
- Ollama ≥ 0.5 with model `llama3.1:8b` (default) or `qwen2.5:7b`; fallback small model `llama3.2:3b`.
- Hardware minimum: 4-core CPU, 8 GB RAM, 10 GB free disk. Recommended: 16 GB RAM; GPU optional.
- Internet required for edge-tts, Pexels and YouTube; LLM runs offline.

### 2.5 Design & Implementation Constraints

- **C-01**: Zero recurring cost. No paid API may be required. Paid providers may exist only as optional plug-ins, disabled by default.
- **C-02**: Language: Python 3.11+, fully type-hinted, packaged with `pyproject.toml`.
- **C-03**: All media processing through FFmpeg invoked via `subprocess` (no MoviePy dependency in the core path).
- **C-04**: Secrets (`client_secret.json`, `token.json`, API keys) must never be committed; stored in `secrets/` and `.env` (git-ignored).
- **C-05**: YouTube API default quota 10,000 units/day; an upload costs ~1,600 units (configurable) → max ~6 uploads/day.
- **C-06**: Videos uploaded from an unverified Google API project are locked to private until the project passes Google's audit. The system must function correctly in this state.
- **C-07**: Pexels content license allows free use; the system records attribution and adds credits to the description.
- **C-08**: Fonts and music must be license-free (e.g., Google Fonts OFL; YouTube Audio Library tracks supplied by user).

### 2.6 Assumptions & Dependencies

- **A-01**: User owns a YouTube channel that is phone-verified (needed for custom thumbnails and > 15-min limits).
- **A-02**: User has created a Google Cloud project with YouTube Data API v3 enabled and an OAuth "Desktop app" client.
- **A-03**: The OAuth consent screen is set to In production (unverified is acceptable for personal use). In "Testing" status Google expires refresh tokens after 7 days — the system must detect and prompt re-auth.
- **A-04**: A local LLM's knowledge is dated; topics should be evergreen AI concepts, or the user supplies source_notes for recent/news topics.
- **A-05**: Default narration language is English (Indian English voice); Hindi is supported via configuration.

## 3. Functional Requirements

Priority: **M** = Must, **S** = Should, **C** = Could.

### 3.1 Topic Management

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | The system shall store topics with fields: id, title, format (short/long/both), level (beginner/intermediate), priority (1–5), optional source_notes, optional keywords, status, created_at. | M |
| FR-02 | The system shall let the user add a topic via CLI and bulk-import topics from data/topics.csv. | M |
| FR-03 | The system shall select the next topic by highest priority, then oldest created_at, skipping topics already produced in the requested format. | M |
| FR-04 | The system shall reject topics not related to the configured niche (content.niche) using an LLM relevance check (score < threshold → rejected with reason), and shall independently reject unsafe content (sexual, graphic violence, hate speech, harassment, illegal activity) regardless of niche. | S |
| FR-05 | The system shall detect near-duplicate topics (case-insensitive fuzzy match ≥ 85%) against produced topics and warn the user. | S |

### 3.2 Script Generation

| ID | Requirement | Priority |
|---|---|---|
| FR-10 | The system shall generate a script as structured JSON validated against a schema (title, hook, scenes[], cta, key_terms). | M |
| FR-11 | Short scripts shall target 75–100 spoken words (30–40 s) with: hook (≤ 3 s), 2–4 content scenes, 1 CTA line. | M |
| FR-12 | Long scripts shall target 600–750 spoken words (4–5 min) with: hook, intro, 5–8 content scenes, recap, CTA. | M |
| FR-13 | Each scene shall specify a visual type (title, bullets, definition, comparison, flow, code, broll) and the fields that type needs. | M |
| FR-14 | Scripts shall use simple language suitable for the topic level, include at least one real-world analogy or example, and avoid unverifiable statistics unless present in source_notes. | M |
| FR-15 | When source_notes exist, the script shall be grounded in them and must not contradict them. | M |
| FR-16 | The user shall be able to view and manually edit the generated script JSON before later stages run. | M |

### 3.3 Script Review (Agent Self-Critique)

| ID | Requirement | Priority |
|---|---|---|
| FR-20 | The system shall run an LLM review producing scores (1–10) for: technical accuracy, clarity, hook strength, beginner-friendliness, structure, and a list of issues. | M |
| FR-21 | If any score < 7 (configurable), the system shall rewrite the script using the review feedback, max 2 rewrite iterations. | M |
| FR-22 | The review shall flag claims involving numbers, dates, product names or "latest" statements as needs_human_check. | M |
| FR-23 | If still below threshold after max iterations, the job shall continue but be marked needs_human_review = true, which forces the approval gate even in auto mode. | M |

### 3.4 Voiceover

| ID | Requirement | Priority |
|---|---|---|
| FR-30 | The system shall synthesize narration per scene using edge-tts with the configured voice, rate and pitch. | M |
| FR-31 | The system shall capture word-level timings for each scene (edge-tts WordBoundary events; fallback: local faster-whisper alignment). | M |
| FR-32 | The system shall measure total narration duration and enforce the format range (Short 30–40 s; Long 240–300 s) by adjusting the speech rate (±15% max) and, if still outside, requesting the LLM to shorten/lengthen (max 2 attempts). | M |
| FR-33 | Pronunciation fixes: the system shall apply a configurable dictionary (e.g., "LLM" → "L L M", "GPT" → "G P T") before TTS, without changing on-screen text. | S |

### 3.5 Subtitles

| ID | Requirement | Priority |
|---|---|---|
| FR-40 | The system shall generate burned-in captions: Short → large centered 1–4-word chunks with active-word highlight; Long → bottom captions, ≤ 2 lines, ≤ 42 chars/line. | M |
| FR-41 | The system shall produce an SRT sidecar for Long videos and optionally upload it as a caption track. | S |

### 3.6 Visuals

| ID | Requirement | Priority |
|---|---|---|
| FR-50 | The system shall render slides with Pillow using brand config (colors, fonts, logo) at the format resolution (Long 1920×1080; Short 1080×1920). | M |
| FR-51 | Supported slide templates: title, bullets (≤ 4), definition (term + one-line definition), comparison (2 columns, ≤ 4 rows), flow (2–5 boxes with arrows), code (≤ 12 lines, monospace). | M |
| FR-52 | The system shall fetch b-roll from Pexels by scene query with orientation matching the format, choose the file closest to the target resolution, and cache downloads. | M |
| FR-53 | If Pexels returns no result or fails, the system shall fall back to a generated slide (title template) — never fail the job for missing b-roll. | M |
| FR-54 | Short videos shall use darkened b-roll background with a top title bar and large captions; Long videos shall mix slides and b-roll (≥ 60% slides). | M |
| FR-55 | The system shall store attribution (photographer, URL) for each Pexels asset used. | M |

### 3.7 Composition

| ID | Requirement | Priority |
|---|---|---|
| FR-60 | The system shall render each scene as a clip whose length equals its narration length plus configurable padding (default 0.25 s). | M |
| FR-61 | The system shall concatenate scene clips, apply short fade transitions, burn captions, optionally mix background music (ducked to −20 dB under voice), and normalize loudness to −14 LUFS. | M |
| FR-62 | Output: H.264 (yuv420p), 30 fps, AAC 48 kHz 192 kbps, MP4 with +faststart. | M |
| FR-63 | The system shall add optional branded intro/outro clips (Long only) and a small logo watermark. | C |
| FR-64 | The system shall validate the output with ffprobe (duration range, resolution, audio present) before marking the stage complete. | M |

### 3.8 Metadata & Thumbnail

| ID | Requirement | Priority |
|---|---|---|
| FR-70 | The system shall generate: title (≤ 70 chars, Short titles include #Shorts), description (hook paragraph, key points, chapters for Long, credits, hashtags, AI-assistance note), tags (total ≤ 450 chars), category 27 (Education). | M |
| FR-71 | Long videos shall include chapters derived from actual scene timestamps (first at 00:00, ≥ 3 chapters, each ≥ 10 s). | M |
| FR-72 | The system shall generate a 1280×720 JPG thumbnail (< 2 MB) for Long videos with ≤ 5 bold words, brand colors and a background frame. | M |

### 3.9 Approval Gate

| ID | Requirement | Priority |
|---|---|---|
| FR-80 | By default (publish.require_approval: true) a rendered job shall stop at status AWAITING_APPROVAL. | M |
| FR-81 | The user shall be able to preview (open file), approve, reject (with reason), or request re-render of a job via CLI. | M |
| FR-82 | Jobs flagged needs_human_review shall always require approval. | M |

### 3.10 YouTube Upload

| ID | Requirement | Priority |
|---|---|---|
| FR-90 | The system shall authenticate with OAuth 2.0 (installed-app flow), persist the refresh token, refresh automatically, and prompt re-auth when the token is invalid/expired. | M |
| FR-91 | The system shall upload using resumable upload with retry and exponential backoff on 5xx/network errors (max 5 retries). | M |
| FR-92 | Upload shall set: title, description, tags, categoryId, defaultLanguage, privacyStatus (config; default private), selfDeclaredMadeForKids=false, containsSyntheticMedia (config), optional publishAt. | M |
| FR-93 | The system shall upload the thumbnail (Long) and SRT captions (Long, optional) after the video upload succeeds. | S |
| FR-94 | The system shall record the video ID, URL and upload time, and must never upload the same job twice (idempotency). | M |
| FR-95 | The system shall track quota usage per Pacific-time day and refuse an upload that would exceed the configured budget. | M |
| FR-96 | A --dry-run mode shall run everything except the API calls and print the request body. | M |

### 3.11 Orchestration, State & Scheduling

| ID | Requirement | Priority |
|---|---|---|
| FR-100 | Each job shall progress through states: NEW → SCRIPTED → REVIEWED → VOICED → VISUALS_READY → RENDERED → METADATA_READY → AWAITING_APPROVAL → APPROVED → UPLOADED (plus FAILED, REJECTED). | M |
| FR-101 | Each stage shall be idempotent, persist its outputs in workspace/jobs/<job_id>/, and be resumable from the last successful stage. | M |
| FR-102 | The system shall provide a daily command producing N Shorts and M Longs (config) and uploading approved jobs within quota. | M |
| FR-103 | The system shall provide scripts to register the daily command with Windows Task Scheduler and cron. | S |
| FR-104 | The system shall clean job working files older than a configurable number of days, keeping final.mp4, script.json and metadata.json. | C |

### 3.12 CLI, Config, Logging

| ID | Requirement | Priority |
|---|---|---|
| FR-110 | The system shall provide a CLI edutube with commands: init, doctor, auth, topic add/import/list, generate, resume, status, edit-script, preview, approve, reject, upload, daily, quota, clean, serve. | M |
| FR-111 | doctor shall verify Python version, FFmpeg/ffprobe, Ollama server & model, fonts, Pexels key, OAuth files, disk space, and print pass/fail per check. | M |
| FR-112 | All behaviour shall be configurable via config.yaml with secrets in .env; config validated at startup with clear errors. | M |
| FR-113 | The system shall log to console (rich) and to rotating file logs/edutube.log, with a per-job log workspace/jobs/<id>/job.log. | M |

### 3.13 Local Web UI

| ID | Requirement | Priority |
|---|---|---|
| FR-120 | `edutube serve` shall launch a local-only (default 127.0.0.1) web server providing: a form to submit a topic and pick Short/Long, a job list, and a per-job page with stage history, video preview, approve/reject, and upload. | S |
| FR-121 | The web UI shall reuse the same orchestrator/pipeline code as the CLI; it shall not duplicate stage logic. | M |
| FR-122 | Video generation and upload triggered from the web UI shall run in a background thread so HTTP requests return immediately; job status shall always be read from the database, never from in-memory state alone, so a server restart does not lose job history. | M |
| FR-123 | The web UI is a local convenience layer, not a hosted service; it shall not be exposed as a requirement to bind beyond localhost, and shall not introduce authentication (out of scope for a single-operator local tool). | S |

## 4. Non-Functional Requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-01 | Cost | Total recurring monetary cost = ₹0 with default configuration. |
| NFR-02 | Performance | On the minimum hardware (CPU only), a Short job (excluding upload) completes in ≤ 8 min; a Long job in ≤ 25 min. |
| NFR-03 | Reliability | Any stage failure leaves prior artifacts intact; resume continues from the failed stage. Network calls use retry with backoff. |
| NFR-04 | Portability | Runs unmodified on Windows, Linux, macOS; all paths via pathlib; no shell-specific syntax in subprocess calls (list args, shell=False). |
| NFR-05 | Security | No secrets in logs or repo; .gitignore covers secrets/, .env, workspace/, logs/. OAuth scopes limited to youtube.upload and youtube.force-ssl (captions). |
| NFR-06 | Maintainability | Modular packages per LLD; type hints; ruff + mypy --strict on core modules clean; each module unit-tested; ≥ 70% line coverage on non-I/O logic. |
| NFR-07 | Testability | All external services behind interfaces with fakes for tests; tests run offline. |
| NFR-08 | Usability | Every CLI error prints a cause and a fix hint. edutube --help documents all commands. |
| NFR-09 | Quality of output | Audio −14 LUFS ±1; no caption overlapping safe zones (Short: bottom 20% and right 15% reserved for YouTube UI). |
| NFR-10 | Compliance | Default human approval ON; AI-assistance note in description; synthetic media flag configurable; attribution for stock media; content limited to AI education. |
| NFR-11 | Extensibility | New LLM/TTS/stock providers addable by implementing one interface and registering in config. |
| NFR-12 | Observability | status shows per-job stage, duration, errors; quota shows today's usage. |

## 5. External Interface Requirements

### 5.1 User Interface

CLI only (Typer + Rich). Tables for lists, progress bars per stage.

### 5.2 Software Interfaces

| Interface | Protocol | Auth | Notes |
|---|---|---|---|
| Ollama | HTTP localhost:11434 via ollama Python lib | none | Structured output with JSON schema |
| edge-tts | WebSocket (library) | none | Needs internet |
| Pexels | HTTPS REST api.pexels.com/videos/search | API key header | 200 req/h, 20k/month |
| YouTube Data API v3 | HTTPS REST (google-api-python-client) | OAuth 2.0 | Quota 10k units/day |
| FFmpeg/ffprobe | Local process | — | ≥ 6.0 |

### 5.3 Files

| File | Purpose |
|---|---|
| config.yaml | All non-secret settings |
| .env | PEXELS_API_KEY, optional provider keys |
| secrets/client_secret.json | Google OAuth client |
| secrets/token.json | Persisted OAuth token |
| data/topics.csv | Topic import |
| data/edutube.db | SQLite state |
| workspace/jobs/<job_id>/ | All job artifacts |

## 6. Acceptance Criteria (System Level)

| ID | Criterion |
|---|---|
| AC-01 | edutube doctor passes all checks on a freshly set-up machine. |
| AC-02 | edutube generate --next --format short produces final.mp4: 1080×1920, 30–40 s, burned captions, audible narration at −14 ±1 LUFS, and stops at AWAITING_APPROVAL. |
| AC-03 | edutube generate --next --format long produces final.mp4: 1920×1080, 240–300 s, ≥ 5 scenes, chapters in metadata, thumbnail 1280×720. |
| AC-04 | edutube approve <id> then edutube upload <id> uploads the video (private), sets thumbnail (Long), stores video ID; running upload again does nothing and reports "already uploaded". |
| AC-05 | Killing the process during VOICED stage and running edutube resume <id> completes the job without regenerating the script. |
| AC-06 | With Pexels key removed, a Short still renders using slide fallbacks. |
| AC-07 | edutube upload <id> --dry-run makes no network call to YouTube and prints the request body. |
| AC-08 | pytest passes offline; coverage report ≥ 70% for content/, media/subtitles.py, pipeline/. |

## 7. Future Enhancements (not in v1.0)

- Web dashboard for review/approval.
- Optional paid providers (Claude API, ElevenLabs) behind existing interfaces.
- Hindi + English dual-audio.
- Analytics-driven topic selection (YouTube Analytics API).
- Local image generation (Stable Diffusion) for custom illustrations.
