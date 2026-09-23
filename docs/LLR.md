# Low-Level Requirements (LLR)

## EduTube Agent

| Field | Value |
|---|---|
| Document ID | EDT-LLR-001 |
| Version | 1.0 |
| Parent | EDT-SRS-001 (docs/SRS.md) |
| Design | EDT-LLD-001 (docs/LLD.md) |

Each requirement is atomic, testable, traced to an SRS requirement (FR/NFR) and assigned a
verification method: **T** = automated test, **I** = code inspection, **D** = manual demo.

Module prefixes map to packages in the LLD:

| Prefix | Module (LLD path) |
|---|---|
| CFG | edutube/config.py |
| DB | edutube/db.py |
| TOP | edutube/content/topics.py |
| LLM | edutube/llm/* |
| SCR | edutube/content/script_writer.py |
| REV | edutube/content/reviewer.py |
| TTS | edutube/media/tts.py |
| SUB | edutube/media/subtitles.py |
| SLD | edutube/media/slides.py |
| STK | edutube/media/stock.py |
| CMP | edutube/media/composer.py, edutube/media/ffmpeg.py |
| THB | edutube/media/thumbnail.py |
| MET | edutube/content/metadata.py |
| AUT | edutube/publish/youtube_auth.py |
| UPL | edutube/publish/uploader.py |
| QTA | edutube/publish/quota.py |
| ORC | edutube/pipeline/orchestrator.py, stages.py |
| CLI | edutube/cli.py |
| LOG | edutube/logging_setup.py |
| SCH | scripts/* |

## 1. Configuration (CFG)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-CFG-01 | Config shall be loaded from config.yaml (path overridable by --config or EDUTUBE_CONFIG) into a Pydantic v2 AppConfig model. | FR-112 | T |
| LLR-CFG-02 | Secrets shall be loaded from environment / .env via pydantic-settings (PEXELS_API_KEY). Secrets shall be SecretStr and never printed. | FR-112, NFR-05 | T |
| LLR-CFG-03 | Invalid config shall raise ConfigError listing every invalid field path and expected type; CLI exits with code 2. | FR-112, NFR-08 | T |
| LLR-CFG-04 | Duration targets shall be config values with defaults: short 30–40 s, long 240–300 s; word targets short 75–100, long 600–750. | FR-11, FR-12 | T |
| LLR-CFG-05 | All relative paths in config shall resolve against the project root (directory of config.yaml) using pathlib.Path. | NFR-04 | T |
| LLR-CFG-06 | edutube init shall create config.yaml, .env.example, data/, secrets/, workspace/, logs/, assets/ if missing, never overwriting existing files. | FR-110 | T |

## 2. Persistence (DB)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-DB-01 | SQLite DB at data/edutube.db shall be created with tables topics, jobs, stage_runs, uploads, quota_usage, asset_cache (schema in LLD §6). | FR-100 | T |
| LLR-DB-02 | Schema migrations shall be versioned via PRAGMA user_version; startup applies pending migrations in order. | NFR-06 | T |
| LLR-DB-03 | All writes shall use transactions; job status updates shall be atomic with the corresponding stage_runs row. | NFR-03 | T |
| LLR-DB-04 | DB access shall go through a Repository class; no raw SQL outside db.py. | NFR-06 | I |

## 3. Topics (TOP)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-TOP-01 | add_topic() shall validate: title 5–120 chars, format ∈ {short,long,both}, level ∈ {beginner,intermediate}, priority 1–5 (default 3). | FR-01 | T |
| LLR-TOP-02 | CSV import shall accept header title,format,level,priority,keywords,source_notes; invalid rows are skipped and reported with row numbers; valid rows are inserted. | FR-02 | T |
| LLR-TOP-03 | next_topic(format) shall return the topic with max priority, then min created_at, whose format matches (or both) and which has no job in that format with status ≠ FAILED/REJECTED. | FR-03 | T |
| LLR-TOP-04 | Duplicate detection shall compare normalized titles (lowercase, stripped punctuation) with difflib.SequenceMatcher ratio ≥ 0.85 and return the matched titles. | FR-05 | T |
| LLR-TOP-05 | Relevance check shall call the LLM with prompts/relevance.md, passing content.niche, returning {fits_niche: bool, score: 0-10, reason}; score < content.min_relevance (default 7) → topic status REJECTED with reason. The prompt also rejects unsafe content (sexual, graphic violence, hate speech, etc.) regardless of niche. | FR-04 | T (fake LLM) |

## 4. LLM Layer (LLM)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-LLM-01 | An abstract LLMProvider shall expose generate_json(system: str, user: str, schema: type[BaseModel], temperature: float) -> BaseModel and health() -> HealthStatus. | NFR-11 | I |
| LLR-LLM-02 | OllamaProvider shall pass schema.model_json_schema() as format, set options={temperature, num_ctx: 8192}, and parse the response with schema.model_validate_json. | FR-10 | T |
| LLR-LLM-03 | On JSON/validation error the provider shall retry up to 3 times, appending the validation error text to the user message. After 3 failures raise LLMOutputError. | FR-10, NFR-03 | T |
| LLR-LLM-04 | Request timeout shall be configurable (default 300 s); connection refusal raises LLMUnavailableError with hint "Run ollama serve". | NFR-08 | T |
| LLR-LLM-05 | Prompts shall be stored as Markdown templates in edutube/llm/prompts/ and rendered with string.Template ($var) — no prompt text hard-coded in Python. | NFR-06 | I |
| LLR-LLM-06 | Every LLM call shall log model, prompt name, duration and token counts (if returned) at DEBUG, and save raw request/response to the job folder llm/<n>_<prompt>.json. | FR-113 | T |

## 5. Script Writer (SCR)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-SCR-01 | Output shall validate against the Script model (LLD §5.3). | FR-10 | T |
| LLR-SCR-02 | Short: scenes count 3–5 (hook + 2–3 content + cta), all visual types restricted to title, bullets, definition, broll. Long: scenes 7–11 including hook, intro, recap, cta roles. | FR-11, FR-12 | T |
| LLR-SCR-03 | Spoken word count (sum of narration words) shall be within target range; if outside by any amount, perform one "adjust length" LLM call; if still outside ±10% raise ScriptLengthError. | FR-11, FR-12 | T |
| LLR-SCR-04 | Per-type field validation: bullets 2–4 items ≤ 8 words each; definition term ≤ 4 words, definition ≤ 20 words; comparison exactly 2 headers, 2–4 rows; flow 2–5 steps ≤ 3 words each; code ≤ 12 lines ≤ 60 chars; broll has broll_query 1–3 words. | FR-13, FR-51 | T |
| LLR-SCR-05 | Long scripts shall contain ≥ 60% non-broll scenes; otherwise the writer converts the excess broll scenes to title type. | FR-54 | T |
| LLR-SCR-06 | Prompt shall inject: topic, level, format, word range, language, source_notes (or "none"), channel style guide from config, and the rule "no statistics/dates unless in source_notes". | FR-14, FR-15 | I |
| LLR-SCR-07 | The writer shall save script.json (pretty, UTF-8) to the job folder; edit-script opens it in $EDITOR/VS Code (code --wait) and re-validates on save; invalid edits are rejected with errors and the previous file restored. | FR-16 | T/D |

## 6. Reviewer (REV)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-REV-01 | Review output shall validate against Review model: scores {accuracy, clarity, hook, beginner_friendly, structure} int 1–10, issues: list[str], human_check_claims: list[str], rewrite_instructions: str. | FR-20, FR-22 | T |
| LLR-REV-02 | Pass condition: all scores ≥ review.min_score (default 7). | FR-21 | T |
| LLR-REV-03 | On fail, call writer rewrite(script, review); re-review; max review.max_iterations (default 2). | FR-21 | T |
| LLR-REV-04 | If final review fails or human_check_claims non-empty → job.needs_human_review = True. | FR-22, FR-23 | T |
| LLR-REV-05 | Save every review as review_<n>.json; final accepted script overwrites script.json and previous versions kept as script_v<n>.json. | FR-101 | T |

## 7. TTS (TTS)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-TTS-01 | Per scene, synthesize audio/scene_<i>.mp3 with edge_tts.Communicate(text, voice, rate, pitch) collecting word boundaries; store audio/scene_<i>.words.json as list of {word, start, end} in seconds (offset/duration ÷ 10^7). | FR-30, FR-31 | T (fake) |
| LLR-TTS-02 | If the installed edge-tts supports the boundary argument, pass boundary="WordBoundary". If no word events are received, run faster-whisper (base model, CPU, int8) with word_timestamps=True on the scene audio. If faster-whisper isn't installed, distribute words evenly across the audio duration. | FR-31 | T |
| LLR-TTS-03 | Before synthesis apply tts.pronunciations dictionary using whole-word, case-sensitive regex replacement on the spoken text only; word timings map back to the original display words by index alignment. | FR-33 | T |
| LLR-TTS-04 | Duration fitting: total = Σ ffprobe durations + padding. If outside range: new_rate = clamp(current × total/target_mid − 1, −15%, +15%) and re-synthesize all scenes once. If still outside: call SCR adjust-length (max 2), then re-synthesize. Else raise DurationFitError. | FR-32 | T |
| LLR-TTS-05 | Network errors retried 3× with exponential backoff (2, 4, 8 s). | NFR-03 | T |
| LLR-TTS-06 | Voice defaults: English en-IN-PrabhatNeural (alt en-IN-NeerjaNeural); Hindi hi-IN-MadhurNeural (alt hi-IN-SwaraNeural). | FR-30 | I |

## 8. Subtitles (SUB)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-SUB-01 | Build a global word timeline by offsetting each scene's words by the scene start time (including padding and intro offset). | FR-40 | T |
| LLR-SUB-02 | Short chunking: groups of 1–4 words, break on punctuation, max 18 chars per chunk; each chunk shown from first word start to last word end (min 0.3 s). | FR-40 | T |
| LLR-SUB-03 | Short ASS style: font from brand config, size 80 px (at 1080 w), bold, white, 6 px black outline, centered, vertical position at 60% of height; active word colored brand.accent using per-word \c override events. | FR-40, NFR-09 | T |
| LLR-SUB-04 | Long chunking: lines ≤ 42 chars, ≤ 2 lines, ≤ 7 s per cue, break at punctuation first; ASS bottom-center, size 48 px, margin-v 60 px, semi-transparent box. | FR-40 | T |
| LLR-SUB-05 | Write subtitles.ass for burn-in and subtitles.srt (Long) with HH:MM:SS,mmm timestamps; SRT cues must not overlap and are strictly increasing. | FR-41 | T |

## 9. Slides (SLD)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-SLD-01 | render_slide(scene, fmt, brand) -> Path shall produce PNG at 1920×1080 (long) or 1080×1920 (short). | FR-50 | T |
| LLR-SLD-02 | Templates: title, bullets, definition, comparison, flow, code per layouts in LLD §8.3. | FR-51 | T |
| LLR-SLD-03 | Text shall auto-fit: start at template max font size, decrease by 4 px until it fits its box (min size; if still overflowing, wrap then truncate with "…" and log WARNING). | FR-50 | T |
| LLR-SLD-04 | Safe margins: 6% horizontal / 8% vertical (Long); Short keeps top 12% for title bar and leaves bottom 20% and right 15% free of important text. | NFR-09 | T |
| LLR-SLD-05 | Fonts: assets/fonts/Poppins-Bold.ttf, Poppins-Regular.ttf, JetBrainsMono-Regular.ttf, NotoSansDevanagari-Regular.ttf (Hindi). Missing font → doctor fails with download hint. | FR-50, FR-111 | T |
| LLR-SLD-06 | The logo (assets/brand/logo.png), if present, is placed top-right at 6% of width with 85% opacity. | FR-63 | T |

## 10. Stock Media (STK)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-STK-01 | Query GET https://api.pexels.com/videos/search?query=<q>&orientation=<portrait\|landscape>&size=medium&per_page=10 with header Authorization: <key>. | FR-52 | T (mocked HTTP) |
| LLR-STK-02 | Selection: exclude videos shorter than the scene duration ÷ 2 and already used in this job; among video_files choose mp4 with height closest to target height (≥ 720); pick top result by relevance order. | FR-52 | T |
| LLR-STK-03 | Cache by Pexels video id in workspace/cache/pexels/<id>_<h>.mp4 with asset_cache row; reuse without re-download. | FR-52 | T |
| LLR-STK-04 | Any HTTP error / empty result / missing key → return None; caller converts scene to title slide and logs WARNING. | FR-53 | T |
| LLR-STK-05 | Record {pexels_id, user_name, user_url, video_url} in assets.json of the job. | FR-55 | T |
| LLR-STK-06 | Respect rate limits: on HTTP 429 wait Retry-After (or 60 s) once, then give up (fallback). | FR-53 | T |

## 11. Composition (CMP)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-CMP-01 | All FFmpeg/ffprobe invocations go through ffmpeg.run(args: list[str]) using subprocess.run(..., shell=False, capture_output=True); non-zero exit raises FFmpegError containing the last 30 stderr lines; command logged at DEBUG. | NFR-04, C-03 | T |
| LLR-CMP-02 | Scene clip duration = audio duration + render.scene_padding (0.25 s) — audio padded with apad. | FR-60 | T |
| LLR-CMP-03 | Slide scene: still image looped, subtle zoom (Ken Burns 1.00→1.05) via zoompan when render.ken_burns: true. B-roll scene: loop/trim, scale-to-cover + center-crop to target resolution; Short b-roll darkened (eq=brightness=-0.25). | FR-60, FR-54 | T |
| LLR-CMP-04 | Each clip: 0.2 s fade-in/out on video; encoded with identical params (libx264, yuv420p, 30 fps, CRF 20, preset medium, AAC 48 kHz stereo 192 kbps) to allow concat demuxer -c copy. | FR-61, FR-62 | T |
| LLR-CMP-05 | Short overlay: top title bar PNG (brand primary, topic title ≤ 5 words) overlaid for the full duration. | FR-54 | T |
| LLR-CMP-06 | Final pass: burn subtitles.ass (ass filter with fontsdir), optional music (random track from assets/music/, looped, volume render.music_volume_db −20 dB, sidechain ducking), loudnorm=I=-14:TP=-1.5:LRA=11, -movflags +faststart. | FR-61 | T |
| LLR-CMP-07 | Windows path escaping for the ass filter: convert to forward slashes and escape : as \:. | NFR-04 | T |
| LLR-CMP-08 | Validation via ffprobe: width/height match, duration within format range (±1 s tolerance), has 1 audio + 1 video stream; failure raises RenderValidationError. | FR-64 | T |
| LLR-CMP-09 | Measure integrated loudness of final output (ebur128) and store in render.json; warn if outside −14 ±1 LUFS. | NFR-09 | T |

## 12. Thumbnail (THB)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-THB-01 | Long only: 1280×720 JPG quality 90, size < 2 MB (reduce quality stepwise if larger). | FR-72 | T |
| LLR-THB-02 | Background: frame at 30% of the first b-roll scene (ffmpeg -ss) or brand gradient if none; left 60% text area with dark overlay. | FR-72 | T |
| LLR-THB-03 | Text: metadata.thumbnail_text (≤ 5 words, uppercase), Poppins-Bold auto-fit, one keyword highlighted in accent color, 8 px stroke. | FR-72 | T |

## 13. Metadata (MET)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-MET-01 | LLM generates Metadata (title, description_intro, key_points[3–6], tags[8–20], hashtags[3], thumbnail_text). | FR-70 | T |
| LLR-MET-02 | Title ≤ 70 chars (truncate at word boundary); Short title ends with #Shorts if not present. No clickbait words from content.banned_title_words. | FR-70 | T |
| LLR-MET-03 | Description assembled by template (LLD §9.2): intro, key points, chapters (Long), credits (Pexels attribution), AI note (content.ai_disclosure_text), hashtags; total ≤ 5000 chars; no < or > characters. | FR-70 | T |
| LLR-MET-04 | Tags: deduplicated, each ≤ 30 chars, total joined length ≤ 450 chars. | FR-70 | T |
| LLR-MET-05 | Chapters: from scene start times of scenes with chapter_title; first 00:00; merge chapters shorter than 10 s into the previous; if < 3 chapters, omit chapter block. | FR-71 | T |
| LLR-MET-06 | Save to metadata.json. | FR-101 | T |

## 14. YouTube Auth (AUT)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-AUT-01 | edutube auth runs InstalledAppFlow.from_client_secrets_file(...).run_local_server(port=0) with scopes youtube.upload and youtube.force-ssl; saves secrets/token.json. | FR-90 | D |
| LLR-AUT-02 | get_credentials() loads token, refreshes if expired; on RefreshError (e.g., invalid_grant) raises AuthExpiredError with hint: "Run edutube auth; set OAuth consent screen to In production to avoid 7-day expiry". | FR-90, A-03 | T |
| LLR-AUT-03 | Token file permissions set to 600 on POSIX. | NFR-05 | T |

## 15. Uploader (UPL)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-UPL-01 | Precondition: job status APPROVED (or auto-approved), no row in uploads for job_id; else raise/skip with message. | FR-94, FR-80 | T |
| LLR-UPL-02 | Request body per LLD §10.2, including status.containsSyntheticMedia from config and publishAt (RFC 3339 UTC) only when privacyStatus=private and schedule configured. | FR-92 | T |
| LLR-UPL-03 | MediaFileUpload(chunksize=8 MiB, resumable=True); loop next_chunk(); retry on HttpError 500/502/503/504 and ConnectionError/TimeoutError, backoff random()*2^n s, max 5. | FR-91 | T |
| LLR-UPL-04 | On success insert uploads row (video_id, url, privacy, uploaded_at) before thumbnail/captions; then update job to UPLOADED. | FR-94 | T |
| LLR-UPL-05 | Thumbnail via thumbnails().set(videoId, media_body); 403 (channel not verified) → WARNING, not failure. | FR-93 | T |
| LLR-UPL-06 | Captions via captions().insert(part="snippet", body={videoId, language, name:"English", isDraft:false}) when publish.upload_captions: true. | FR-93 | T |
| LLR-UPL-07 | --dry-run: print JSON body and file sizes; no API client construction. | FR-96 | T |
| LLR-UPL-08 | Handle quotaExceeded (403) → mark quota exhausted for the day and stop further uploads. | FR-95 | T |

## 16. Quota (QTA)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-QTA-01 | Costs from config: videos_insert: 1600, thumbnails_set: 50, captions_insert: 400; daily budget default 10000; safety margin 500. | FR-95 | T |
| LLR-QTA-02 | Day key = current date in America/Los_Angeles (quota resets at Pacific midnight). | FR-95 | T |
| LLR-QTA-03 | can_spend(units) returns False if used + units > budget − margin; record(units, op) persists. | FR-95 | T |

## 17. Orchestrator (ORC)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-ORC-01 | Stage order and resulting statuses as defined in LLD §7.1; each stage implements Stage.run(ctx) -> None and Stage.is_done(ctx) -> bool (checks its output files + validity). | FR-100, FR-101 | T |
| LLR-ORC-02 | run_job(job_id) skips stages where is_done is True, runs the rest; on exception records stage_runs(status=failed, error), sets job FAILED with failed_stage, re-raises a user-friendly error. | FR-101, NFR-03 | T |
| LLR-ORC-03 | resume(job_id) resets FAILED → last successful status and calls run_job. --from-stage <name> deletes outputs of that stage and all following stages before running. | FR-101 | T |
| LLR-ORC-04 | After METADATA_READY: if require_approval or needs_human_review → AWAITING_APPROVAL; else → APPROVED. | FR-80, FR-82 | T |
| LLR-ORC-05 | A job lock file workspace/jobs/<id>/.lock prevents concurrent runs of the same job; stale locks (> 2 h) are removed. | NFR-03 | T |
| LLR-ORC-06 | daily: create schedule.shorts_per_day short jobs and schedule.longs_per_day long jobs from next_topic, run them sequentially, then upload all APPROVED jobs (oldest first) while quota allows. | FR-102 | T |

## 18. CLI (CLI)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-CLI-01 | Implemented with Typer; entry point edutube = edutube.cli:app in pyproject.toml. | FR-110 | I |
| LLR-CLI-02 | Commands and options exactly as LLD §11. | FR-110 | T (CliRunner) |
| LLR-CLI-03 | Exit codes: 0 ok, 1 runtime error, 2 config/usage error, 3 external service unavailable, 4 quota exhausted. | NFR-08 | T |
| LLR-CLI-04 | Errors derived from EdutubeError print ✖ <message> and → Fix: <hint>; tracebacks only with --debug. | NFR-08 | T |
| LLR-CLI-05 | doctor checks listed in FR-111, each printed as PASS/WARN/FAIL row; exit 1 if any FAIL. | FR-111 | T |
| LLR-CLI-06 | preview <id> opens final.mp4 using the OS default player (os.startfile / open / xdg-open). | FR-81 | D |

## 19. Logging (LOG)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-LOG-01 | Root logger: Rich console handler (INFO, DEBUG with --debug) + RotatingFileHandler logs/edutube.log (5 MB × 5). | FR-113 | T |
| LLR-LOG-02 | Per-job file handler added during run_job writing to workspace/jobs/<id>/job.log, removed afterwards. | FR-113 | T |
| LLR-LOG-03 | A redaction filter masks values of known secret keys and Authorization headers. | NFR-05 | T |

## 20. Scheduling Scripts (SCH)

| ID | Requirement | Trace | Verify |
|---|---|---|---|
| LLR-SCH-01 | scripts/schedule_windows.ps1 registers a Task Scheduler task "EduTube Daily" running edutube daily at a configurable time, in the project directory, using the venv Python. | FR-103 | D |
| LLR-SCH-02 | scripts/schedule_cron.sh prints/installs a crontab line running edutube daily with cd into the project and venv activation, logging to logs/cron.log. | FR-103 | D |
| LLR-SCH-03 | edutube clean --older-than 14 removes job subfolders audio/, slides/, clips/, llm/ for jobs older than N days, keeping final.mp4, script.json, metadata.json, thumbnail.jpg. | FR-104 | T |

## 21. Traceability Summary (SRS → LLR)

| SRS | LLR |
|---|---|
| FR-01–05 | TOP-01…05 |
| FR-10–16 | LLM-01…05, SCR-01…07 |
| FR-20–23 | REV-01…05 |
| FR-30–33 | TTS-01…06 |
| FR-40–41 | SUB-01…05 |
| FR-50–55 | SLD-01…06, STK-01…06, SCR-05 |
| FR-60–64 | CMP-01…09 |
| FR-70–72 | MET-01…06, THB-01…03 |
| FR-80–82 | ORC-04, CLI-06, UPL-01 |
| FR-90–96 | AUT-01…03, UPL-01…08, QTA-01…03 |
| FR-100–104 | ORC-01…06, SCH-01…03, DB-01…04 |
| FR-110–113 | CLI-01…06, CFG-01…06, LOG-01…03 |
| NFR-03/04/05/08/09 | LLM-03, TTS-05, CMP-01/07, AUT-03, LOG-03, CLI-03/04, SLD-04, CMP-09 |
