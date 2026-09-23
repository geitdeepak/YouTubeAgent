# EduTube Agent — Instructions for Claude Code

## What this project is
A free, local Python CLI agent that creates AI-education YouTube videos
(Shorts 30-40 s vertical, and Long 4-5 min horizontal) and uploads them.
Pipeline: topic -> script (Ollama) -> self-review -> voice (edge-tts) ->
visuals (Pillow slides + Pexels b-roll) -> render (FFmpeg) -> metadata +
thumbnail -> human approval -> YouTube upload (Data API v3).

## Source of truth
- docs/SRS.md (what) - requirement IDs FR-xx / NFR-xx / AC-xx
- docs/LLR.md (testable module rules) - IDs LLR-<MOD>-xx
- docs/LLD.md (how) - structure, models, schema, algorithms, commands
Always read the relevant sections before coding. If code and docs disagree,
the docs win; if the docs are ambiguous or contradictory, STOP and ask.
Reference requirement IDs in docstrings, tests and commit messages.

## Hard constraints
- Zero cost: never add a paid API or SaaS dependency (SRS C-01).
- FFmpeg via subprocess list args, shell=False (C-03, LLR-CMP-01). No MoviePy.
- Python 3.11+, full type hints, pydantic v2, pathlib everywhere.
- Must work on Windows, Linux and macOS (NFR-04).
- Never commit or print secrets (.env, secrets/). Never hard-code keys.
- Prompts live in src/edutube/llm/prompts/*.md, not in Python code.
- All external services behind interfaces with fakes for tests; tests run offline.
- Default privacy "private" and approval required. Do not change these defaults.

## Commands
- Setup: python -m venv .venv && activate && pip install -e ".[dev]"
- Lint: ruff check . && ruff format --check .
- Types: mypy src
- Tests: pytest -q (unit/component, offline)
- Render tests: pytest -m ffmpeg
- App: edutube --help

## Working rules
1. Work in the phases below, one phase at a time.
2. For each phase: plan briefly -> implement -> write tests -> run ruff, mypy,
   pytest -> fix -> summarize what was done and which LLR IDs are satisfied.
3. Keep functions small and pure where possible; put I/O at the edges.
4. Every stage writes its outputs into workspace/jobs/<job_id>/ and must be
   idempotent (is_done() checks outputs).
5. Log every FFmpeg command at DEBUG. On failure, show the last stderr lines.
6. Commit after each green phase: "phase N: <summary> (LLR-...)".

## Phases
1. Skeleton: pyproject, layout, config, models, errors, logging, db, CLI init/doctor/topic/status.
2. LLM + topics + script writer + reviewer + ScriptStage/ReviewStage + orchestrator skeleton.
3. TTS + alignment + duration fit + subtitles + VoiceStage.
4. Slides (7 templates, both formats) + Pexels stock + VisualStage + preview script.
5. FFmpeg wrapper + composer + RenderStage + integration test.
6. Metadata + thumbnail + MetadataStage + approval gate + generate/resume/edit/preview/approve/reject.
7. YouTube auth + quota + uploader + UploadStage + auth/upload/quota commands.
8. daily + clean + scheduling scripts + README + full acceptance run (SRS §6).
9. (post-v1.0) Configurable niche (content.niche threaded through every prompt,
   not hardcoded to AI) + local web UI (src/edutube/web/, `edutube serve`,
   optional [web] extra) reusing the same orchestrator/pipeline code as the CLI.
