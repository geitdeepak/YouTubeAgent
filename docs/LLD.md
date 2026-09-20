# Low-Level Design (LLD)

## EduTube Agent

| Field | Value |
|---|---|
| Document ID | EDT-LLD-001 |
| Version | 1.0 |
| Implements | EDT-SRS-001, EDT-LLR-001 |

## 1. Architecture Overview

EduTube Agent uses a **staged-pipeline agent** architecture. A deterministic orchestrator runs stages
in order. LLM-driven stages (script, review, metadata) act as the agent's "brain"; the other stages are
tools (TTS, stock search, slide rendering, FFmpeg, YouTube API). Every stage reads and writes files in
the job folder, so any stage can be re-run or resumed on its own.

```
CLI (Typer) --------> Orchestrator (run_job / resume / daily)
                          |  JobContext (config, repo, paths, providers)
   +----------+----------+---------+---------+-----------+-----------+-----------+
   v          v          v         v         v           v           v
ScriptStage ReviewStage VoiceStage VisualStage RenderStage MetadataStage UploadStage
   |          |          |         |         |           |           |
LLMProvider LLMProvider TTSProvider SlideRenderer Composer LLMProvider YouTubeUploader
(Ollama)    (Ollama)   (edge-tts)  StockProvider (FFmpeg)  Thumbnail   QuotaTracker
             Aligner    (Pexels)   Subtitles              YouTubeAuth
```

### Layers

| Layer | Packages | Responsibility |
|---|---|---|
| Interface | cli.py | Parse commands, print results, map errors to exit codes |
| Application | pipeline/ | Orchestration, job state machine, stage execution |
| Domain | models.py, content/ | Pydantic models, script/review/metadata logic |
| Infrastructure | llm/, media/, publish/, db.py | External services, FFmpeg, SQLite, file I/O |

## 2. Technology Stack (pinned minimums)

| Purpose | Package | Version |
|---|---|---|
| Runtime | Python | ≥ 3.11 |
| CLI | typer, rich | ≥ 0.12, ≥ 13.7 |
| Models / config | pydantic, pydantic-settings, PyYAML | ≥ 2.7, ≥ 2.3, ≥ 6.0 |
| LLM | ollama | ≥ 0.4 |
| TTS | edge-tts | ≥ 6.1 |
| Alignment (optional) | faster-whisper | ≥ 1.0 |
| HTTP | httpx | ≥ 0.27 |
| Images | Pillow | ≥ 10.3 |
| YouTube | google-api-python-client, google-auth-oauthlib, google-auth-httplib2 | ≥ 2.130, ≥ 1.2, ≥ 0.2 |
| Retry | tenacity | ≥ 8.3 |
| Timezone | tzdata (Windows) | latest |
| Dev | pytest, pytest-mock, pytest-cov, respx, ruff, mypy | latest |
| Binary | FFmpeg + ffprobe | ≥ 6.0 |
| Binary | Ollama | ≥ 0.5 |

## 3. Repository Layout

```
edutube-agent/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── config.yaml               # created by `edutube init`
├── .env.example               # PEXELS_API_KEY=
├── .gitignore                 # .env, secrets/, workspace/, logs/, data/*.db, .venv/
├── docs/  SRS.md LLR.md LLD.md
├── assets/
│   ├── fonts/   Poppins-Bold.ttf, Poppins-Regular.ttf, JetBrainsMono-Regular.ttf, NotoSansDevanagariRegular.ttf
│   ├── brand/   logo.png (optional), intro.mp4 / outro.mp4 (optional)
│   └── music/   *.mp3 (optional, royalty-free, user supplied)
├── data/  topics.csv, edutube.db (runtime)
├── secrets/   client_secret.json, token.json  (git-ignored)
├── workspace/  jobs/<job_id>/..., cache/pexels/  (git-ignored)
├── logs/
├── scripts/  schedule_windows.ps1, schedule_cron.sh
├── src/edutube/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── errors.py
│   ├── db.py
│   ├── logging_setup.py
│   ├── llm/
│   │   ├── base.py            # LLMProvider ABC
│   │   ├── ollama_provider.py
│   │   ├── fake_provider.py   # for tests
│   │   └── prompts/           # relevance.md, script_short.md, script_long.md, review.md, rewrite.md, adjust_length.md, metadata.md
│   ├── content/
│   │   ├── topics.py
│   │   ├── script_writer.py
│   │   ├── reviewer.py
│   │   └── metadata.py
│   ├── media/
│   │   ├── ffmpeg.py          # run(), probe(), loudness()
│   │   ├── tts.py             # TTSProvider, EdgeTTSProvider, Aligner
│   │   ├── subtitles.py
│   │   ├── slides.py
│   │   ├── stock.py           # StockProvider, PexelsProvider
│   │   ├── composer.py
│   │   └── thumbnail.py
│   ├── publish/
│   │   ├── youtube_auth.py
│   │   ├── uploader.py
│   │   └── quota.py
│   ├── pipeline/
│   │   ├── context.py         # JobContext, JobPaths
│   │   ├── stages.py          # Stage ABC + 7 stages
│   │   └── orchestrator.py
│   └── utils/
│       ├── text.py            # word count, normalize, chunking helpers
│       ├── timeutil.py        # sec <-> SRT/ASS timestamps, Pacific day
│       └── fs.py              # atomic write, lock file, open_file()
└── tests/
    ├── conftest.py            # tmp project, fake providers, sample script fixtures
    ├── fixtures/               # sample script.json, words.json, 1s tone mp3, png
    ├── unit/                   # one test file per module
    └── integration/            # end-to-end with fakes + real ffmpeg (marked `ffmpeg`)
```

## 4. Configuration

### 4.1 config.yaml (default created by `edutube init`)

```yaml
project:
  channel_name: "AI Simplified"
  language: "en"              # en | hi
  timezone: "Asia/Kolkata"

llm:
  provider: "ollama"
  model: "llama3.1:8b"
  host: "http://localhost:11434"
  temperature: 0.7
  review_temperature: 0.2
  timeout_s: 300
  num_ctx: 8192

content:
  niche: "AI education"
  min_relevance: 7
  style_guide: >
    Friendly teacher tone. Explain like to a smart beginner. One analogy per concept.
    Short sentences. No hype, no clickbait. Avoid statistics and dates unless in source notes.
  banned_title_words: ["shocking", "insane", "you won't believe"]
  ai_disclosure_text: "This video was produced with AI assistance (script drafting and synthetic voice) and reviewed by the creator."

formats:
  short:
    width: 1080
    height: 1920
    min_s: 30
    max_s: 40
    min_words: 75
    max_words: 100
  long:
    width: 1920
    height: 1080
    min_s: 240
    max_s: 300
    min_words: 600
    max_words: 750

review:
  min_score: 7
  max_iterations: 2

tts:
  provider: "edge"
  voices:
    en: "en-IN-PrabhatNeural"
    hi: "hi-IN-MadhurNeural"
  rate: "+0%"
  pitch: "+0Hz"
  pronunciations:
    "LLM": "L L M"
    "LLMs": "L L Ms"
    "GPT": "G P T"
    "RAG": "rag"
    "API": "A P I"
    "GPU": "G P U"
    "NLP": "N L P"
  aligner_fallback: "faster-whisper"   # faster-whisper | even

stock:
  provider: "pexels"
  enabled: true
  min_height: 720

brand:
  primary: "#1E3A8A"
  accent: "#FACC15"
  background: "#0B1020"
  text: "#FFFFFF"
  font_bold: "assets/fonts/Poppins-Bold.ttf"
  font_regular: "assets/fonts/Poppins-Regular.ttf"
  font_mono: "assets/fonts/JetBrainsMono-Regular.ttf"
  font_hindi: "assets/fonts/NotoSansDevanagari-Regular.ttf"
  logo: "assets/brand/logo.png"
  intro_clip: null
  outro_clip: null

render:
  fps: 30
  crf: 20
  preset: "medium"
  scene_padding_s: 0.25
  fade_s: 0.2
  ken_burns: true
  music_enabled: true
  music_dir: "assets/music"
  music_volume_db: -20
  target_lufs: -14

publish:
  require_approval: true
  privacy_status: "private"      # private | unlisted | public
  contains_synthetic_media: true
  upload_captions: true
  category_id: "27"
  default_language: "en"
  schedule_publish_time: null    # e.g. "18:00" local -> publishAt next day

quota:
  daily_budget: 10000
  safety_margin: 500
  costs:
    videos_insert: 1600
    thumbnails_set: 50
    captions_insert: 400

schedule:
  shorts_per_day: 1
  longs_per_day: 0
  run_time: "06:00"

paths:
  db: "data/edutube.db"
  workspace: "workspace"
  logs: "logs"
  secrets: "secrets"
  topics_csv: "data/topics.csv"
```

### 4.2 config.py design

```python
class FormatSpec(BaseModel):
    width: int; height: int; min_s: float; max_s: float; min_words: int; max_words: int
    @property
    def target_s(self) -> float: return (self.min_s + self.max_s) / 2

class AppConfig(BaseModel):
    project: ProjectCfg; llm: LLMCfg; content: ContentCfg
    formats: dict[Literal["short","long"], FormatSpec]
    review: ReviewCfg; tts: TTSCfg; stock: StockCfg; brand: BrandCfg
    render: RenderCfg; publish: PublishCfg; quota: QuotaCfg
    schedule: ScheduleCfg; paths: PathsCfg
    root: Path = Field(exclude=True)     # directory containing config.yaml
    def resolve(self, p: str | Path) -> Path   # root / p if relative

class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    pexels_api_key: SecretStr | None = None

def load_config(path: Path | None = None) -> AppConfig   # raises ConfigError
```

## 5. Domain Models (models.py)

### 5.1 Enums

```python
class VideoFormat(StrEnum): SHORT = "short"; LONG = "long"
class TopicFormat(StrEnum): SHORT = "short"; LONG = "long"; BOTH = "both"
class Level(StrEnum): BEGINNER = "beginner"; INTERMEDIATE = "intermediate"
class TopicStatus(StrEnum): ACTIVE = "active"; REJECTED = "rejected"; ARCHIVED = "archived"
class SceneRole(StrEnum): HOOK="hook"; INTRO="intro"; CONTENT="content"; RECAP="recap"; CTA="cta"
class VisualType(StrEnum):
    TITLE="title"; BULLETS="bullets"; DEFINITION="definition"
    COMPARISON="comparison"; FLOW="flow"; CODE="code"; BROLL="broll"
class JobStatus(StrEnum):
    NEW="NEW"; SCRIPTED="SCRIPTED"; REVIEWED="REVIEWED"; VOICED="VOICED"
    VISUALS_READY="VISUALS_READY"; RENDERED="RENDERED"; METADATA_READY="METADATA_READY"
    AWAITING_APPROVAL="AWAITING_APPROVAL"; APPROVED="APPROVED"; UPLOADED="UPLOADED"
    FAILED="FAILED"; REJECTED="REJECTED"
```

### 5.2 Topic & Job

```python
class Topic(BaseModel):
    id: int | None = None
    title: str = Field(min_length=5, max_length=120)
    format: TopicFormat = TopicFormat.BOTH
    level: Level = Level.BEGINNER
    priority: int = Field(3, ge=1, le=5)
    keywords: list[str] = []
    source_notes: str | None = None
    status: TopicStatus = TopicStatus.ACTIVE
    reject_reason: str | None = None
    created_at: datetime

class Job(BaseModel):
    id: str    # f"{yyyymmdd}-{format}-{slug[:30]}-{4 hex}"
    topic_id: int
    format: VideoFormat
    language: str
    status: JobStatus
    failed_stage: str | None = None
    last_error: str | None = None
    needs_human_review: bool = False
    reject_reason: str | None = None
    created_at: datetime; updated_at: datetime
```

### 5.3 Script (LLM output contract)

```python
class Comparison(BaseModel):
    headers: tuple[str, str]
    rows: list[tuple[str, str]] = Field(min_length=2, max_length=4)

class Scene(BaseModel):
    index: int
    role: SceneRole
    visual: VisualType
    narration: str                        # spoken text (display form)
    on_screen_title: str = Field(max_length=60)
    chapter_title: str | None = None      # Long only; used for chapters
    bullets: list[str] | None = None      # BULLETS
    term: str | None = None               # DEFINITION
    definition: str | None = None         # DEFINITION
    comparison: Comparison | None = None  # COMPARISON
    flow_steps: list[str] | None = None   # FLOW
    code: str | None = None               # CODE
    code_language: str | None = None
    broll_query: str | None = None        # BROLL
    @model_validator(mode="after")
    def check_visual_fields(self) -> "Scene": ...   # LLR-SCR-04 rules

class Script(BaseModel):
    topic_title: str
    format: VideoFormat
    language: str
    title: str
    hook: str
    scenes: list[Scene] = Field(min_length=3, max_length=11)
    key_terms: list[str] = []
    @property
    def word_count(self) -> int: return sum(count_words(s.narration) for s in self.scenes)
```

**LLM-facing schema**: Send the LLM a *simplified* JSON schema (the same fields but without
validators). Validate strictly afterwards with the model above. Small local models follow flat
schemas more reliably.

### 5.4 Review, Metadata, Media records

```python
class Scores(BaseModel):
    accuracy: int = Field(ge=1, le=10); clarity: int = Field(ge=1, le=10)
    hook: int = Field(ge=1, le=10); beginner_friendly: int = Field(ge=1, le=10)
    structure: int = Field(ge=1, le=10)

class Review(BaseModel):
    scores: Scores
    issues: list[str]
    human_check_claims: list[str]
    rewrite_instructions: str
    def passed(self, min_score: int) -> bool: ...

class Word(BaseModel): word: str; start: float; end: float
class SceneAudio(BaseModel):
    index: int; path: Path; duration: float; words: list[Word]
class VoiceResult(BaseModel):
    scenes: list[SceneAudio]; rate: str; total_duration: float
class SceneVisual(BaseModel):
    index: int; kind: Literal["slide", "broll"]; path: Path
    fallback_used: bool = False
class StockAttribution(BaseModel):
    pexels_id: int; user_name: str; user_url: str; video_url: str
class VideoMetadata(BaseModel):
    title: str; description_intro: str; key_points: list[str]
    tags: list[str]; hashtags: list[str]; thumbnail_text: str
    description: str = ""                 # assembled final description
    chapters: list[tuple[str, str]] = []  # ("00:00", "Intro")
class RenderInfo(BaseModel):
    path: Path; duration: float; width: int; height: int; lufs: float
    scene_starts: list[float]
```

## 6. Database Schema (db.py)

```sql
-- user_version = 1
CREATE TABLE topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  title_norm TEXT NOT NULL,
  format TEXT NOT NULL CHECK (format IN ('short','long','both')),
  level TEXT NOT NULL DEFAULT 'beginner',
  priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  keywords TEXT NOT NULL DEFAULT '[]',    -- JSON array
  source_notes TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  reject_reason TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX ix_topics_pick ON topics(status, priority DESC, created_at);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  topic_id INTEGER NOT NULL REFERENCES topics(id),
  format TEXT NOT NULL,
  language TEXT NOT NULL,
  status TEXT NOT NULL,
  failed_stage TEXT,
  last_error TEXT,
  needs_human_review INTEGER NOT NULL DEFAULT 0,
  reject_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX ix_jobs_status ON jobs(status);
CREATE INDEX ix_jobs_topic ON jobs(topic_id, format);

CREATE TABLE stage_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  stage TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running','done','failed','skipped')),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  duration_s REAL,
  error TEXT
);

CREATE TABLE uploads (
  job_id TEXT PRIMARY KEY REFERENCES jobs(id),
  video_id TEXT NOT NULL UNIQUE,
  url TEXT NOT NULL,
  privacy TEXT NOT NULL,
  thumbnail_set INTEGER NOT NULL DEFAULT 0,
  captions_set INTEGER NOT NULL DEFAULT 0,
  uploaded_at TEXT NOT NULL
);

CREATE TABLE quota_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day_pt TEXT NOT NULL,   -- YYYY-MM-DD (America/Los_Angeles)
  op TEXT NOT NULL,
  units INTEGER NOT NULL,
  job_id TEXT,
  at TEXT NOT NULL
);
CREATE INDEX ix_quota_day ON quota_usage(day_pt);

CREATE TABLE asset_cache (
  key TEXT PRIMARY KEY,   -- e.g. "pexels:123456:1080"
  path TEXT NOT NULL,
  meta TEXT NOT NULL,     -- JSON
  created_at TEXT NOT NULL
);
```

### Repository API

```python
class Repository:
    def __init__(self, db_path: Path) -> None   # connects, WAL mode, migrates
    # topics
    def add_topic(self, t: Topic) -> int
    def list_topics(self, status: TopicStatus | None = None) -> list[Topic]
    def get_topic(self, topic_id: int) -> Topic
    def set_topic_status(self, topic_id: int, status: TopicStatus, reason: str | None) -> None
    def next_topic(self, fmt: VideoFormat) -> Topic | None    # LLR-TOP-03 query
    # jobs
    def create_job(self, job: Job) -> None
    def get_job(self, job_id: str) -> Job
    def list_jobs(self, status: JobStatus | None = None, limit: int = 50) -> list[Job]
    def update_job(self, job_id: str, **fields) -> None
    # stages
    def start_stage(self, job_id: str, stage: str) -> int
    def finish_stage(self, run_id: int, status: str, error: str | None = None) -> None
    # uploads / quota / cache
    def record_upload(self, ...) -> None; def get_upload(self, job_id: str) -> dict | None
    def add_quota(self, day_pt: str, op: str, units: int, job_id: str | None) -> None
    def quota_used(self, day_pt: str) -> int
    def cache_get(self, key: str) -> dict | None; def cache_put(self, key, path, meta) -> None
```

`next_topic` SQL:

```sql
SELECT t.* FROM topics t
WHERE t.status = 'active'
  AND t.format IN (:fmt, 'both')
  AND NOT EXISTS (
    SELECT 1 FROM jobs j WHERE j.topic_id = t.id AND j.format = :fmt
      AND j.status NOT IN ('FAILED','REJECTED'))
ORDER BY t.priority DESC, t.created_at ASC
LIMIT 1;
```

## 7. Pipeline Design

### 7.1 State Machine

```
NEW --ScriptStage--> SCRIPTED --ReviewStage--> REVIEWED --VoiceStage--> VOICED
  --VisualStage--> VISUALS_READY --RenderStage--> RENDERED --MetadataStage--> METADATA_READY
  --(approval gate)--> AWAITING_APPROVAL --approve--> APPROVED --UploadStage--> UPLOADED
                                          \--reject--> REJECTED
any stage exception --> FAILED (failed_stage=<name>) --resume--> previous good status
```

| # | Stage class | Input files | Output files (job folder) | Status on success |
|---|---|---|---|---|
| 1 | ScriptStage | topic (DB) | script.json, llm/*.json | SCRIPTED |
| 2 | ReviewStage | script.json | review_<n>.json, script_v<n>.json, script.json | REVIEWED |
| 3 | VoiceStage | script.json | audio/scene_<i>.mp3, audio/scene_<i>.words.json, voice.json | VOICED |
| 4 | VisualStage | script.json, voice.json | slides/scene_<i>.png, broll/scene_<i>.mp4, visuals.json, assets.json, overlay_title.png (short) | VISUALS_READY |
| 5 | RenderStage | all above | clips/scene_<i>.mp4, concat.txt, subtitles.ass, subtitles.srt, final.mp4, render.json | RENDERED |
| 6 | MetadataStage | script.json, render.json, assets.json | metadata.json, thumbnail.jpg (long) | METADATA_READY → gate |
| 7 | UploadStage | final.mp4, metadata.json, thumbnail.jpg, subtitles.srt | upload.json | UPLOADED |

The approval gate is **not** a stage. It is a transition applied by the orchestrator after stage 6
(LLR-ORC-04). UploadStage runs only when the user calls `edutube upload`, or during `daily` for
APPROVED jobs.

### 7.2 Context & Stage interfaces (pipeline/context.py, stages.py)

```python
@dataclass
class JobPaths:
    root: Path
    @property
    def script(self) -> Path: return self.root / "script.json"
    # ...similar properties for every file in the table above
    def ensure(self) -> None   # mkdir audio/ slides/ broll/ clips/ llm/

@dataclass
class JobContext:
    job: Job
    topic: Topic
    cfg: AppConfig
    secrets: Secrets
    repo: Repository
    paths: JobPaths
    llm: LLMProvider
    tts: TTSProvider
    stock: StockProvider | None
    fmt: FormatSpec         # cfg.formats[job.format]
    dry_run: bool = False

class Stage(ABC):
    name: ClassVar[str]
    success_status: ClassVar[JobStatus]
    @abstractmethod
    def run(self, ctx: JobContext) -> None: ...
    @abstractmethod
    def is_done(self, ctx: JobContext) -> bool: ...
    def outputs(self, ctx: JobContext) -> list[Path]: ...   # used by --from-stage cleanup
```

### 7.3 Orchestrator algorithm

```python
PIPELINE = [ScriptStage(), ReviewStage(), VoiceStage(), VisualStage(), RenderStage(), MetadataStage()]

def run_job(job_id: str, *, dry_run=False) -> Job:
    ctx = build_context(job_id, dry_run)
    with job_lock(ctx.paths.root), job_log_handler(ctx.paths.root / "job.log"):
        for stage in PIPELINE:
            if stage.is_done(ctx):
                log.info("skip %s (done)", stage.name); continue
            run_id = repo.start_stage(job_id, stage.name)
            try:
                stage.run(ctx)
                repo.finish_stage(run_id, "done")
                repo.update_job(job_id, status=stage.success_status, failed_stage=None, last_error=None)
            except Exception as e:
                repo.finish_stage(run_id, "failed", error=str(e))
                repo.update_job(job_id, status=JobStatus.FAILED, failed_stage=stage.name, last_error=str(e))
                raise StageFailedError(stage.name, e) from e
        gate = (cfg.publish.require_approval or ctx.job.needs_human_review)
        repo.update_job(job_id, status=AWAITING_APPROVAL if gate else APPROVED)
    return repo.get_job(job_id)

def resume(job_id, from_stage: str | None = None):
    if from_stage: delete outputs of from_stage and every later stage
    return run_job(job_id)

def daily():
    for fmt, n in [(SHORT, cfg.schedule.shorts_per_day), (LONG, cfg.schedule.longs_per_day)]:
        for _ in range(n):
            topic = repo.next_topic(fmt)
            if not topic: log.warning("no topics for %s", fmt); break
            job = create_job(topic, fmt)
            try: run_job(job.id)
            except StageFailedError: continue    # next job
    for job in repo.list_jobs(APPROVED) sorted by created_at:
        if not quota.can_spend(cost_of_upload(job)): break
        UploadStage().run(build_context(job.id))
```

## 8. Component Design

### 8.1 LLM layer

```python
class LLMProvider(ABC):
    @abstractmethod
    def generate_json(self, *, prompt_name: str, variables: dict[str, str],
                       schema: type[T], temperature: float, log_dir: Path | None) -> T: ...
    @abstractmethod
    def health(self) -> HealthStatus: ...   # server reachable, model pulled

class OllamaProvider(LLMProvider):
    def __init__(self, cfg: LLMCfg): self.client = ollama.Client(host=cfg.host, timeout=cfg.timeout_s)
    def generate_json(...):
        system, user = render_prompt(prompt_name, variables)   # split on line "---USER---"
        schema_json = llm_schema(schema)   # simplified schema
        msgs = [{"role":"system","content":system},{"role":"user","content":user}]
        for attempt in range(1, 4):
            resp = self.client.chat(model=cfg.model, messages=msgs, format=schema_json,
                                     options={"temperature": temperature, "num_ctx": cfg.num_ctx})
            raw = resp["message"]["content"]; save_log(...)
            try: return schema.model_validate_json(raw)
            except ValidationError as e:
                msgs += [{"role":"assistant","content":raw},
                         {"role":"user","content":f"Your JSON was invalid:\n{e}\nReturn corrected JSON only."}]
        raise LLMOutputError(prompt_name)
```

Prompt template format (llm/prompts/*.md):

```
You are an expert AI educator writing for the YouTube channel "$channel_name".
Style guide: $style_guide
---USER---
Topic: $topic
Level: $level
Format: $format ($min_s-$max_s seconds, $min_words-$max_words spoken words total)
Language: $language
Source notes (ground truth, may be "none"): $source_notes
Rules:
1. Scene plan: $scene_plan
2. Allowed visual types: $visual_types
3. Every scene narration must be natural spoken language, no markdown, no emojis.
4. Include one real-world analogy.
5. No statistics, dates, version numbers or "latest" claims unless present in source notes.
6. on_screen_title max 6 words. bullets max 8 words each.
Return ONLY JSON matching the schema.
```

`scene_plan` values:
- short: "Scene 1 role=hook (1 sentence, a question or surprising fact about the concept). Scenes 2-3
  role=content. Last scene role=cta: 'Follow for more AI in 40 seconds.'"
- long: "Scene 1 hook (15-20s), scene 2 intro (what you will learn), scenes 3-8 content (one idea
  each, mix of definition/bullets/flow/comparison/code/broll, max 40% broll), recap scene (bullets of
  3 takeaways), final cta scene (subscribe + next topic tease). Give every scene a chapter_title of
  1-4 words."

Prompts to create: `relevance.md`, `script_short.md`, `script_long.md`, `review.md` (rubric with 1–10
anchors for every score), `rewrite.md` (inputs: script JSON + review JSON), `adjust_length.md` (inputs:
script JSON, current words, target range, "shorten"/"lengthen"), `metadata.md`.

### 8.2 TTS & alignment (media/tts.py)

```python
class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, out_mp3: Path, *, voice: str, rate: str, pitch: str) -> list[Word]: ...

class EdgeTTSProvider(TTSProvider):
    def synthesize(...):
        spoken = apply_pronunciations(text, cfg.tts.pronunciations)
        words = asyncio.run(self._stream(spoken, out_mp3, voice, rate, pitch))
        if not words: words = self.aligner.align(out_mp3, spoken)
        return remap_to_display_words(words, text, spoken)

    async def _stream(...):
        kwargs = {"boundary": "WordBoundary"} if "boundary" in signature(Communicate).parameters else {}
        comm = edge_tts.Communicate(spoken, voice, rate=rate, pitch=pitch, **kwargs)
        with open(out_mp3, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio": f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    s = chunk["offset"] / 1e7; d = chunk["duration"] / 1e7
                    words.append(Word(word=chunk["text"], start=s, end=s + d))
```

Duration-fit algorithm (VoiceStage.run):

```python
rate = cfg.tts.rate  # e.g. "+0%"
for attempt in 0..2:
    synthesize all scenes -> durations d_i
    total = Σ d_i + n_scenes * padding
    if fmt.min_s <= total <= fmt.max_s: break
    if attempt == 0:
        pct = round((total / fmt.target_s - 1) * 100)   # speed up if too long
        pct = clamp(current_pct + pct, -15, +15); rate = f"{pct:+d}%"; continue
    # rate adjustment insufficient -> change the text
    script = writer.adjust_length(script, total, fmt)   # LLM
    save script.json; rate = cfg.tts.rate
else: raise DurationFitError(total, fmt)
write voice.json
```

### 8.3 Slides (media/slides.py)

Canvas W×H from the format. Units: `u = W/100`. All colors from `brand`.

| Template | Long layout (1920×1080) | Short layout (1080×1920) |
|---|---|---|
| Background (all) | Vertical gradient background → 15% lighter; 6 px accent bar at the left edge; logo top-right | Same; title bar reserved at top 12% |
| title | on_screen_title centered, Bold 110→60 px, accent underline 40% width | Centered at 40% height, Bold 96→56 px |
| bullets | Title top-left (Bold 72 px) at (6%, 10%); bullets start at 30% height, Regular 52→36 px, accent "●" markers, 1.6 line spacing | Title at 16%; bullets from 30% to 70% height, 60→40 px |
| definition | Term Bold 120 px accent color, centered at 38%; definition Regular 56 px, wrapped at 70% width, centered at 60% | Term at 35%, definition at 50% |
| comparison | Two rounded cards (radius 24) 42% width each, 6% gap; headers Bold 60 px on primary-colored header strip; rows Regular 44 px with divider lines | Cards stacked vertically (top/bottom) |
| flow | N boxes horizontally spaced evenly between 6%–94%, rounded, primary fill, text Bold 44 px; arrows (accent, 8 px line + triangle head) between them | Boxes stacked vertically with down-arrows |
| code | Dark panel (#111827) 88% width with 3 window dots; JetBrains Mono 40 px; basic keyword coloring for Python (def, return, import, from, class, for, in, if) | Same, 34 px, max 10 lines |

Helper functions:

```python
def fit_text(draw, text, font_path, max_w, max_h, start_size, min_size, line_spacing=1.25) -> tuple[ImageFont, list[str]]
def wrap_lines(text, font, max_w) -> list[str]
def draw_gradient(img, top_hex, bottom_hex) -> None
def rounded_box(draw, xyxy, radius, fill, outline=None) -> None
def arrow(draw, start, end, color, width) -> None
def render_title_bar(title, fmt, brand) -> Path   # Short overlay_title.png (RGBA, transparent below bar)
```

For Hindi (`language == "hi"`), use `font_hindi` for all body text. Pillow needs `libraqm` for correct
Devanagari shaping: `doctor` warns if `features.check("raqm")` is False.

### 8.4 Stock (media/stock.py)

```python
class StockProvider(ABC):
    @abstractmethod
    def fetch_video(self, query: str, *, orientation: str, min_duration: float,
                     target_height: int, exclude_ids: set[int], dest_dir: Path) -> tuple[Path, StockAttribution] | None: ...

class PexelsProvider(StockProvider):
    BASE = "https://api.pexels.com/videos/search"
    # httpx.Client(timeout=30, headers={"Authorization": key})
    # params: query, orientation ('portrait' short / 'landscape' long), size='medium', per_page=10
    # choose: first v in videos where v.id not in exclude and v.duration >= min_duration/2;
    #   file = min((f for f in v.video_files if f.file_type=='video/mp4' and f.height>=min_height),
    #              key=lambda f: abs(f.height - target_height))
    # cache key f"pexels:{v.id}:{file.height}"; stream download to cache dir; copy/hardlink into job broll/
```

Query enrichment: if a `broll_query` has one word, append a context word from a safe list
("technology", "computer", "data") to get more relevant results.

### 8.5 Subtitles (media/subtitles.py)

```python
def build_timeline(voice: VoiceResult, scene_starts: list[float]) -> list[Word]
def chunk_short(words: list[Word], max_words=4, max_chars=18) -> list[Cue]
def chunk_long(words: list[Word], max_chars=42, max_lines=2, max_dur=7.0) -> list[Cue]
def to_ass_short(cues, fmt, brand) -> str   # karaoke-style active word highlight
def to_ass_long(cues, fmt, brand) -> str
def to_srt(cues) -> str
def fmt_ass_time(sec) -> str   # H:MM:SS.cc
def fmt_srt_time(sec) -> str   # HH:MM:SS,mmm
```

**Short active-word highlight**: for each chunk, emit one Dialogue event per word. The event runs
from that word's start to the next word's start (the last word runs to the chunk end). Its text is the
full chunk, with the active word wrapped in `{\c&H<BGR>&}word{\c&HFFFFFF&}`. ASS colors are
`&HBBGGRR&`, so convert the brand hex.

ASS header (Short):

```
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Poppins,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,5,80,160,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.20,0:00:01.55,Cap,,0,0,0,,{\pos(540,1150)}WHAT IS {\c&H15CCFA&}RAG{\c&HFFFFFF&}
```

(Alignment 5 = middle-center; `\pos` places captions at 60% height, above YouTube's bottom UI.)

### 8.6 Composer (media/composer.py, media/ffmpeg.py)

```python
def run(args: list[str], *, cwd: Path | None = None) -> str
def probe(path: Path) -> ProbeInfo   # ffprobe -v error -show_entries format=duration:stream=codec_type,width,height -of json
def loudness(path: Path) -> float    # ffmpeg -i f -af ebur128=framelog=quiet -f null - -> parse "I:" value
def ff_filter_path(p: Path) -> str   # forward slashes; escape ':' -> '\:' (Windows drive), "'" -> "\\'"
```

Common encode args `ENC`: `-c:v libx264 -preset {preset} -crf {crf} -pix_fmt yuv420p -r {fps} -c:a aac -b:a 192k -ar 48000 -ac 2`

Slide scene clip (with Ken Burns):

```
ffmpeg -y -loop 1 -framerate {fps} -i slides/scene_i.png -i audio/scene_i.mp3
  -filter_complex "[0:v]scale={W*2}:{H*2},zoompan=z='min(zoom+0.0005,1.05)':d={frames}:s={W}x{H}:fps={fps},
    fade=t=in:st=0:d={fade},fade=t=out:st={dur-fade}:d={fade}[v];
    [1:a]apad=pad_dur={padding}[a]"
  -map "[v]" -map "[a]" -t {dur} {ENC} clips/scene_i.mp4
```

where `dur = audio_duration + padding` and `frames = ceil(dur * fps)`. Without Ken Burns: `scale={W}:{H}` only.

B-roll scene clip:

```
ffmpeg -y -stream_loop -1 -i broll/scene_i.mp4 -i audio/scene_i.mp3
  -filter_complex "[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={fps}
    {,eq=brightness=-0.25:saturation=0.9 (short only)}
    {,overlay lower-third title PNG (long only)}
    ,fade=t=in:st=0:d={fade},fade=t=out:st={dur-fade}:d={fade}[v];
    [1:a]apad=pad_dur={padding}[a]"
  -map "[v]" -map "[a]" -t {dur} {ENC} clips/scene_i.mp4
```

Concat (identical encoding enables stream copy):

```
concat.txt: file 'clips/scene_0.mp4'   (one line per clip; add intro/outro clips re-encoded with ENC if configured)
ffmpeg -y -f concat -safe 0 -i concat.txt -c copy joined.mp4
```

Final pass (captions, overlay, music, loudness):

```
ffmpeg -y -i joined.mp4 [-i overlay_title.png] [-stream_loop -1 -i music.mp3]
  -filter_complex "
    [0:v][1:v]overlay=0:0[vo];                     (short: title bar)
    [vo]ass='{ff_filter_path(subtitles.ass)}':fontsdir='{ff_filter_path(assets/fonts)}'[v];
    [2:a]volume={music_db}dB[m];
    [m][0:a]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300[md];
    [0:a][md]amix=inputs=2:duration=first:normalize=0,
    loudnorm=I={lufs}:TP=-1.5:LRA=11[a]"
  -map "[v]" -map "[a]" {ENC} -movflags +faststart final.mp4
```

Without music: `[0:a]loudnorm=...[a]`. Build the filter graph programmatically from the parts that apply.

Scene start times (`render.json.scene_starts`): cumulative sum of clip durations, plus the intro clip
duration if used. Subtitles and chapters both use these.

**Validation**: `probe(final)` must return width and height equal to the format, one video stream and
one audio stream, and a duration within `[min_s − 1, max_s + 1]`. Measure lufs and store it.

### 8.7 Thumbnail (media/thumbnail.py)

```python
def make_thumbnail(ctx, meta: VideoMetadata) -> Path:
    bg = extract_frame(first_broll, at=0.3) or gradient(brand)   # ffmpeg -ss {t} -i f -frames:v 1 -q:v 2
    img = cover_resize(bg, 1280, 720); darken left 60% (alpha 170 black gradient)
    words = meta.thumbnail_text.upper().split()[:5]
    font, lines = fit_text(..., max_w=700, max_h=520, start=150, min=80)
    draw lines with stroke_width=8 stroke_fill=black; longest keyword in brand.accent
    logo bottom-left 90 px
    save JPEG q=90; while size > 2 MB: q -= 10
```

### 8.8 Metadata (content/metadata.py)

Description template:

```
{description_intro}

In this video:
• {key_point_1}
• ...

{"Chapters:" block if long}
00:00 {chapter_1}
01:12 {chapter_2}
...

Credits:
Stock footage from Pexels — {user_name} ({video_url})  (one line per asset)

{ai_disclosure_text}

{#hashtag1 #hashtag2 #hashtag3}  {#Shorts if short}
```

- Remove `<` and `>` characters. Truncate key_points if total exceeds 5000 chars.
- Chapter timestamps: MM:SS (or H:MM:SS if ≥ 1 h), taken from scene starts of scenes with a chapter_title.

### 8.9 YouTube auth & upload (publish/)

```python
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]

def run_auth_flow(cfg) -> None
def get_credentials(cfg) -> Credentials    # refresh or raise AuthExpiredError
def youtube_client(creds) -> Resource      # build("youtube", "v3", credentials=creds, cache_discovery=False)
```

Upload request body:

```json
{
  "snippet": {
    "title": "...", "description": "...", "tags": ["..."],
    "categoryId": "27", "defaultLanguage": "en", "defaultAudioLanguage": "en"
  },
  "status": {
    "privacyStatus": "private",
    "selfDeclaredMadeForKids": false,
    "containsSyntheticMedia": true,
    "publishAt": "2026-09-21T12:30:00Z"
  }
}
```

Include `publishAt` only when `schedule_publish_time` is set and `privacyStatus == "private"`.

Resumable upload loop:

```python
req = yt.videos().insert(part="snippet,status", body=body,
        media_body=MediaFileUpload(final, chunksize=8*1024*1024, resumable=True, mimetype="video/mp4"))
response, retry = None, 0
while response is None:
    try:
        status, response = req.next_chunk()
        if status: progress.update(status.progress())
    except HttpError as e:
        if e.resp.status in (500, 502, 503, 504): retry += 1
        elif e.resp.status == 403 and "quotaExceeded" in str(e): raise QuotaExhaustedError
        else: raise UploadError(e)
    except (ConnectionError, TimeoutError, httplib2.HttpLib2Error): retry += 1
    if retry > 5: raise UploadError("max retries")
    if retry: time.sleep(random.random() * 2 ** retry)
video_id = response["id"]
quota.record(cost.videos_insert, "videos.insert", job_id)
repo.record_upload(job_id, video_id, f"https://youtu.be/{video_id}", privacy)
# then thumbnail (long) + captions (long, if enabled) — each failure = WARNING
repo.update_job(job_id, status=UPLOADED); write upload.json
```

### 8.10 Quota (publish/quota.py)

```python
class QuotaTracker:
    def day_key(self) -> str: return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    def used(self) -> int
    def can_spend(self, units: int) -> bool: return self.used() + units <= budget - margin
    def record(self, units: int, op: str, job_id: str | None) -> None
    def mark_exhausted(self) -> None   # records remaining units as "exhausted"
def upload_cost(job, cfg) -> int   # insert + thumbnail(long) + captions(long & enabled)
```

## 9. Error Handling

```python
class EdutubeError(Exception):
    exit_code = 1; hint = ""
class ConfigError(EdutubeError): exit_code = 2
class ServiceUnavailableError(EdutubeError): exit_code = 3
class LLMUnavailableError(ServiceUnavailableError): hint = "Start Ollama: `ollama serve`, then `ollama pull <model>`"
class LLMOutputError(EdutubeError): hint = "Try a larger model (llama3.1:8b/qwen2.5:7b) or lower temperature"
class ScriptLengthError(EdutubeError): hint = "Run `edutube edit-script <id>` or `resume --from-stage script`"
class DurationFitError(EdutubeError): hint = "Edit narration length, then `edutube resume <id> --from-stage voice`"
class FFmpegError(EdutubeError): hint = "Run `edutube doctor`; see job.log for the ffmpeg command"
class RenderValidationError(EdutubeError)
class AuthExpiredError(EdutubeError): hint = "Run `edutube auth`. Set the OAuth consent screen to 'In production'"
class UploadError(EdutubeError)
class QuotaExhaustedError(EdutubeError): exit_code = 4; hint = "Quota resets at midnight Pacific Time"
class StageFailedError(EdutubeError)   # wraps the stage name and cause
```

Retry policy (tenacity): edge-tts and Pexels use 3 attempts with exponential backoff (2–8 s). Ollama
uses its own validation-retry loop only. Network retries for YouTube use the custom loop in §8.9.

## 10. Logging

- Format: `%(asctime)s | %(levelname)-7s | %(name)s | %(message)s`
- Logger names: `edutube.<module>`
- RedactFilter masks `PEXELS_API_KEY` values, `Authorization`, `access_token`, `refresh_token`, `client_secret`.

## 11. CLI Specification (cli.py)

| Command | Options | Behaviour |
|---|---|---|
| edutube init | --force-config | Create folders and default files (LLR-CFG-06) |
| edutube doctor | | Environment checks (Python, ffmpeg ≥ 6, ffprobe, Ollama reachable, model pulled, fonts, raqm (hi), Pexels key, client_secret.json, token.json, disk ≥ 5 GB) |
| edutube auth | | OAuth flow → secrets/token.json |
| edutube topic add "<title>" | --format short\|long\|both, --level, --priority, --keywords a,b, --notes-file path, --skip-check | Validate, relevance check, duplicate warning, insert |
| edutube topic import | --file data/topics.csv | Bulk import with row report |
| edutube topic list | --status | Rich table |
| edutube generate | --topic-id N \| --next, --format short\|long (required), --lang en\|hi, --dry-run | Create job and run pipeline up to the approval gate |
| edutube resume <job_id> | --from-stage script\|review\|voice\|visuals\|render\|metadata | Resume or partially re-run |
| edutube status | [job_id], --status | List jobs or show stage history for one job |
| edutube edit-script <job_id> | | Open script.json in VS Code (code --wait), fall back to $EDITOR/notepad; re-validate |
| edutube preview <job_id> | | Open final.mp4 |
| edutube approve <job_id> | | AWAITING_APPROVAL → APPROVED |
| edutube reject <job_id> | --reason "..." | → REJECTED |
| edutube upload <job_id> | --dry-run | Upload APPROVED job |
| edutube daily | --no-upload | Batch run (LLR-ORC-06) |
| edutube quota | | Today's usage and remaining uploads |
| edutube clean | --older-than 14 | Cleanup (LLR-SCH-03) |
| Global | --config PATH, --debug | |

## 12. Sequence — Short video, end to end

```
User -> CLI: generate --next --format short
CLI -> Orchestrator: create job
Orchestrator -> Ollama: ScriptStage -> JSON script
Orchestrator -> Ollama: ReviewStage -> scores (rewrite if <7)
Orchestrator -> edge-tts: VoiceStage -> mp3 + word timings (x scenes); duration fit (rate adj / LLM adjust)
Orchestrator -> Pexels: VisualStage -> b-roll (portrait) / slide fallback; Pillow slides + title bar
Orchestrator -> FFmpeg: RenderStage -> clips, concat, captions, loudnorm
Orchestrator -> Ollama: MetadataStage -> title/desc/tags (#Shorts)
Orchestrator -> CLI: AWAITING_APPROVAL
User -> CLI: preview / approve / upload
CLI -> Orchestrator -> YouTube: UploadStage -> videos.insert -> video URL (private)
```

## 13. Testing Strategy

| Level | Scope | Tools |
|---|---|---|
| Unit | models validators, text utils, chunking, ASS/SRT formatting, time formatting, chapter building, tag trimming, quota math, next_topic SQL, pronunciation remap, ff_filter_path escaping, FFmpeg arg builders (compare lists) | pytest |
| Component | OllamaProvider with mocked client (invalid → retry → valid), Pexels with respx, EdgeTTS with a monkeypatched Communicate, uploader with a fake MediaFileUpload/HttpError sequence | pytest-mock, respx |
| Integration (-m ffmpeg) | Full pipeline with FakeLLMProvider (fixture scripts), FakeTTSProvider (generates sine-tone mp3 of the right length with ffmpeg sine), stock disabled → real render of Short and Long; assert probe results | real ffmpeg |
| Manual | edutube auth, real upload in private, scheduling scripts | D |

Fixtures: `tests/fixtures/script_short.json` (4 scenes, 90 words) and `script_long.json` (9 scenes, 680
words). They must cover every visual type.

CI (optional): GitHub Actions on `ubuntu-latest` installs ffmpeg with apt, then runs `ruff`, `mypy`, and
`pytest -m "not manual"`.

## 14. Performance Notes

- Render scene clips sequentially. A `render.parallel_clips` option (default 1) may use a
  ThreadPoolExecutor, because FFmpeg itself is multi-threaded.
- Use `preset veryfast` for the Short previews if the render time exceeds the NFR-02 target on slow
  machines (configurable).
- Keep the Ollama model loaded between stages (`keep_alive: "10m"` in the options).

## 15. Security & Compliance Checklist

- [ ] .gitignore includes .env, secrets/, workspace/, logs/, data/*.db
- [ ] OAuth scopes limited to upload + force-ssl
- [ ] Default privacy_status: private and require_approval: true
- [ ] AI disclosure text in the description; containsSyntheticMedia is configurable
- [ ] Pexels attribution in the description
- [ ] Music only from the user-provided royalty-free folder
- [ ] Topic relevance filter keeps the channel on AI education
