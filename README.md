# EduTube Agent

A free, local AI agent that writes, produces and uploads AI-education videos to
YouTube: **Shorts** (30-40s, 9:16) and **Long** videos (4-5 min, 16:9).

Pipeline: topic queue -> script (local LLM via Ollama) -> self-review -> voice
(edge-tts) -> visuals (Pillow slides + Pexels b-roll) -> render (FFmpeg) ->
metadata + thumbnail -> human approval gate -> YouTube upload.

Zero recurring cost: every component is free (Ollama, edge-tts, Pexels free
tier, FFmpeg, the YouTube Data API's free daily quota).

Full specification: [docs/SRS.md](docs/SRS.md) (requirements),
[docs/LLR.md](docs/LLR.md) (module-level rules), [docs/LLD.md](docs/LLD.md)
(design). [CLAUDE.md](CLAUDE.md) has build-phase notes for AI coding assistants.

## Requirements

- Python 3.11+
- FFmpeg + ffprobe >= 6.0 on PATH
- [Ollama](https://ollama.com) with a pulled model (`llama3.1:8b` recommended;
  `llama3.2:3b` if you have less than ~12 GB RAM, at the cost of weaker
  structured-output compliance -- see Troubleshooting)
- A Pexels API key (free) for stock b-roll -- optional, the system falls back
  to generated slides without one
- A Google Cloud project with the YouTube Data API v3 enabled and an OAuth
  "Desktop app" client -- only needed for the `upload` command

## Setup

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

# 2. Install the package
pip install -e ".[dev]"

# 3. Pull an LLM model
ollama pull llama3.1:8b

# 4. Initialize the project (creates config.yaml, data/, secrets/, workspace/, logs/)
edutube init

# 5. Add your Pexels key (optional)
copy .env.example .env
notepad .env

# 6. Verify everything
edutube doctor
```

To enable YouTube upload later:

1. Create a Google Cloud project, enable **YouTube Data API v3**.
2. OAuth consent screen -> External -> add yourself as a test user -> **publish
   to production** (avoids the 7-day token expiry that applies in Testing mode).
3. Credentials -> Create OAuth client ID -> Desktop app -> download the JSON as
   `secrets/client_secret.json`.
4. Run `edutube auth` once and sign in with the channel's Google account.

Videos uploaded from an unverified Google API project stay **private** until
Google audits the project -- review and publish them manually in YouTube
Studio, or apply for the audit.

## Daily use

```powershell
# Add topics (or bulk-import from data/topics.csv)
edutube topic add "What is RAG (Retrieval-Augmented Generation)?" --format both --priority 5
edutube topic import --file data/topics.csv

# Produce a video
edutube generate --next --format short
edutube generate --next --format long

# Review
edutube status
edutube preview <job_id>
edutube edit-script <job_id>     # tweak the script before re-rendering if needed

# Approve and upload
edutube approve <job_id>
edutube upload <job_id>
edutube upload <job_id> --dry-run   # print the request body, no network call

# Automate
edutube daily                    # generate + upload today's batch
edutube quota                    # see remaining YouTube API quota
edutube clean --older-than 14    # delete intermediate files for old jobs
```

### Scheduling

```powershell
# Windows: registers a daily Task Scheduler job
powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1
```

```bash
# Linux/macOS/WSL: prints (or installs) a crontab line
scripts/schedule_cron.sh --install
```

## Project layout

```
config.yaml       # all non-secret settings
.env              # PEXELS_API_KEY (git-ignored)
secrets/          # OAuth client_secret.json, token.json (git-ignored)
data/             # topics.csv, edutube.db (git-ignored)
workspace/jobs/   # per-job artifacts: script.json, audio/, slides/, final.mp4... (git-ignored)
assets/           # fonts, brand logo, royalty-free music
src/edutube/      # application source
tests/            # pytest unit + integration tests
```

## Testing

```powershell
ruff check .
mypy src
pytest -q                 # offline unit/component tests
pytest -q -m ffmpeg        # + integration tests that render real video with FFmpeg
pytest -q --cov=edutube --cov-report=term-missing
```

## Troubleshooting

- **`edutube doctor` fails on Ollama**: run `ollama serve`, then `ollama pull
  llama3.1:8b`.
- **Script generation repeatedly fails validation**: the model isn't reliably
  following the strict per-field JSON constraints (word/line limits). Try a
  larger/more capable model (`llama3.1:8b`, `qwen2.5:7b`) or lower
  `llm.temperature` in config.yaml.
- **`edutube auth` token expires every 7 days**: the OAuth consent screen is
  still in "Testing" -- publish it to "In production" (personal/unverified use
  is fine).
- **Render fails partway through**: `edutube resume <job_id>` continues from
  the last successful stage; `edutube resume <job_id> --from-stage voice`
  re-runs a specific stage onward.
