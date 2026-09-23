"""CLI entry point (LLD §11, LLR-CLI-01..06)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from edutube import __version__
from edutube.config import AppConfig, Secrets, load_config, load_secrets
from edutube.content import topics as topics_mod
from edutube.db import Repository
from edutube.errors import EdutubeError
from edutube.logging_setup import setup_logging
from edutube.models import JobStatus, Level, Topic, TopicFormat, TopicStatus, VideoFormat
from edutube.pipeline import orchestrator
from edutube.utils.fs import open_file

app = typer.Typer(add_completion=False, help="EduTube Agent -- AI-education video generator and uploader")
topic_app = typer.Typer(help="Manage the topic queue")
app.add_typer(topic_app, name="topic")

console = Console()

_config_path: Path | None = None
_debug: bool = False


@app.callback()
def main(
    config: Path | None = typer.Option(None, "--config", help="Path to config.yaml"),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks and debug logging"),
) -> None:
    global _config_path, _debug
    _config_path = config
    _debug = debug


def _project_root() -> Path:
    if _config_path:
        return _config_path.resolve().parent
    return Path.cwd()


def _load() -> tuple[AppConfig, Secrets, Repository]:
    cfg = load_config(_config_path)
    setup_logging(cfg.resolve(cfg.paths.logs), debug=_debug)
    secrets = load_secrets(cfg.resolve(".env"))
    repo = Repository(cfg.resolve(cfg.paths.db))
    return cfg, secrets, repo


def _fail(e: EdutubeError) -> None:
    console.print(f"[bold red]✖[/bold red] {e.message if hasattr(e, 'message') else e}")
    if e.hint:
        console.print(f"[yellow]→ Fix:[/yellow] {e.hint}")
    if _debug:
        raise e
    raise typer.Exit(code=e.exit_code)


# ---- init / doctor ------------------------------------------------------


@app.command()
def init(force_config: bool = typer.Option(False, "--force-config", help="Overwrite existing config.yaml")) -> None:
    """Create folders and default files (LLR-CFG-06)."""
    root = _project_root()
    for d in ("data", "secrets", "workspace", "logs", "assets/fonts", "assets/brand", "assets/music"):
        (root / d).mkdir(parents=True, exist_ok=True)

    config_path = root / "config.yaml"
    if config_path.exists() and not force_config:
        console.print(f"[yellow]config.yaml already exists, not overwriting: {config_path}[/yellow]")
    else:
        default_cfg = _default_config_yaml(root)
        config_path.write_text(default_cfg, encoding="utf-8")
        console.print(f"[green]Created {config_path}[/green]")

    env_example = root / ".env.example"
    if not env_example.exists():
        env_example.write_text("PEXELS_API_KEY=\n", encoding="utf-8")
        console.print(f"[green]Created {env_example}[/green]")

    console.print("[bold green]edutube init complete.[/bold green] Run `edutube doctor` next.")


def _default_config_yaml(root: Path) -> str:
    # Rendered from AppConfig defaults so it always matches the current schema.
    import yaml

    cfg = AppConfig(root=root)
    data = cfg.model_dump(mode="json", exclude={"root"})
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


@app.command()
def doctor() -> None:
    """Verify the environment: Python, FFmpeg, Ollama, fonts, keys, disk space (FR-111)."""
    root = _project_root()
    checks: list[tuple[str, str, str]] = []  # (name, status, detail)

    checks.append(("Python", "PASS" if sys.version_info >= (3, 11) else "FAIL", sys.version.split()[0]))

    ffmpeg_path = shutil.which("ffmpeg")
    checks.append(("FFmpeg", "PASS" if ffmpeg_path else "FAIL", ffmpeg_path or "not found on PATH"))
    ffprobe_path = shutil.which("ffprobe")
    checks.append(("ffprobe", "PASS" if ffprobe_path else "FAIL", ffprobe_path or "not found on PATH"))

    try:
        cfg = load_config(_config_path)
        checks.append(("config.yaml", "PASS", "loaded"))
    except EdutubeError as e:
        checks.append(("config.yaml", "FAIL", str(e)))
        cfg = None

    if cfg is not None:
        try:
            from edutube.llm.ollama_provider import OllamaProvider

            health = OllamaProvider(cfg.llm).health()
            checks.append(("Ollama", "PASS" if health.ok else "FAIL", health.detail))
        except Exception as e:  # noqa: BLE001
            checks.append(("Ollama", "FAIL", str(e)))

        for name, rel in [
            ("Font Poppins-Bold", cfg.brand.font_bold),
            ("Font Poppins-Regular", cfg.brand.font_regular),
            ("Font JetBrains Mono", cfg.brand.font_mono),
            ("Font Noto Sans Devanagari", cfg.brand.font_hindi),
        ]:
            path = cfg.resolve(rel)
            checks.append((name, "PASS" if path.exists() else "WARN", str(path)))

        try:
            from PIL import features

            checks.append(("Pillow raqm (Hindi shaping)", "PASS" if features.check("raqm") else "WARN", ""))
        except Exception:  # noqa: BLE001
            checks.append(("Pillow raqm (Hindi shaping)", "WARN", "could not check"))

        secrets = load_secrets(cfg.resolve(".env"))
        pexels_detail = "set" if secrets.pexels_api_key else "missing (b-roll will fall back to slides)"
        checks.append(("Pexels API key", "PASS" if secrets.pexels_api_key else "WARN", pexels_detail))

        client_secret = cfg.resolve(cfg.paths.secrets) / "client_secret.json"
        checks.append(("OAuth client_secret.json", "PASS" if client_secret.exists() else "WARN", str(client_secret)))
        token = cfg.resolve(cfg.paths.secrets) / "token.json"
        token_detail = str(token) if token.exists() else "run `edutube auth`"
        checks.append(("OAuth token.json", "PASS" if token.exists() else "WARN", token_detail))

    try:
        usage = shutil.disk_usage(root)
        free_gb = usage.free / (1024**3)
        checks.append(("Disk space", "PASS" if free_gb >= 5 else "WARN", f"{free_gb:.1f} GB free"))
    except OSError as e:
        checks.append(("Disk space", "WARN", str(e)))

    table = Table(title="edutube doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    any_fail = False
    for name, status, detail in checks:
        color = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}[status]
        table.add_row(name, f"[{color}]{status}[/{color}]", detail)
        if status == "FAIL":
            any_fail = True
    console.print(table)
    if any_fail:
        raise typer.Exit(code=1)


# ---- auth -----------------------------------------------------------------


@app.command()
def auth() -> None:
    """Run the OAuth installed-app flow and save secrets/token.json (LLR-AUT-01)."""
    from edutube.publish.youtube_auth import run_auth_flow

    try:
        cfg, _secrets, _repo = _load()
        client_secret = cfg.resolve(cfg.paths.secrets) / "client_secret.json"
        token_path = cfg.resolve(cfg.paths.secrets) / "token.json"
        run_auth_flow(client_secret, token_path)
        console.print("[bold green]Authenticated.[/bold green]")
    except EdutubeError as e:
        _fail(e)


# ---- topics -----------------------------------------------------------------


@topic_app.command("add")
def topic_add(
    title: str = typer.Argument(...),
    format_: str = typer.Option("both", "--format", help="short|long|both"),
    level: str = typer.Option("beginner", "--level"),
    priority: int = typer.Option(3, "--priority"),
    keywords: str = typer.Option("", "--keywords", help="comma-separated"),
    notes_file: Path | None = typer.Option(None, "--notes-file"),
    skip_check: bool = typer.Option(False, "--skip-check", help="Skip the LLM relevance check"),
) -> None:
    try:
        cfg, _secrets, repo = _load()
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        notes = notes_file.read_text(encoding="utf-8") if notes_file else None
        llm = None
        if not skip_check:
            try:
                from edutube.llm.ollama_provider import OllamaProvider

                llm = OllamaProvider(cfg.llm)
            except Exception:  # noqa: BLE001
                llm = None
        topic = topics_mod.add_topic(
            repo,
            title=title,
            fmt=TopicFormat(format_),
            level=Level(level),
            priority=priority,
            keywords=kw_list,
            source_notes=notes,
            llm=llm,
            niche=cfg.content.niche,
            min_relevance=cfg.content.min_relevance,
            skip_check=skip_check,
        )
        status_note = f" (status={topic.status.value})" if topic.status != TopicStatus.ACTIVE else ""
        console.print(f"[green]Added topic #{topic.id}: {topic.title}{status_note}[/green]")
    except EdutubeError as e:
        _fail(e)


@topic_app.command("import")
def topic_import(file: Path = typer.Option(..., "--file")) -> None:
    try:
        _cfg, _secrets, repo = _load()
        report = topics_mod.import_csv(repo, file)
        console.print(f"[green]Imported {report.inserted} topics.[/green]")
        for row_num, reason in report.skipped:
            console.print(f"[yellow]  row {row_num}: skipped ({reason})[/yellow]")
    except EdutubeError as e:
        _fail(e)
    except (OSError, ValueError) as e:
        console.print(f"[bold red]✖[/bold red] {e}")
        raise typer.Exit(code=1) from e


@topic_app.command("list")
def topic_list(status: str | None = typer.Option(None, "--status")) -> None:
    try:
        _cfg, _secrets, repo = _load()
        status_enum = TopicStatus(status) if status else None
        rows = repo.list_topics(status_enum)
        table = Table(title="Topics")
        for col in ("id", "title", "format", "level", "priority", "status", "created_at"):
            table.add_column(col)
        for t in rows:
            table.add_row(
                str(t.id), t.title, t.format.value, t.level.value, str(t.priority), t.status.value, str(t.created_at)
            )
        console.print(table)
    except EdutubeError as e:
        _fail(e)


# ---- generate / resume / status / edit-script / preview / approve / reject ------


@app.command()
def generate(
    topic_id: int | None = typer.Option(None, "--topic-id"),
    next_: bool = typer.Option(False, "--next"),
    format_: str = typer.Option(..., "--format", help="short|long"),
    lang: str | None = typer.Option(None, "--lang"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        cfg, secrets, repo = _load()
        fmt = VideoFormat(format_)
        topic: Topic
        if topic_id is not None:
            topic = repo.get_topic(topic_id)
        elif next_:
            next_topic = repo.next_topic(fmt)
            if next_topic is None:
                console.print("[yellow]No topics available for this format.[/yellow]")
                raise typer.Exit(code=1)
            topic = next_topic
        else:
            console.print("[red]Specify --topic-id or --next[/red]")
            raise typer.Exit(code=2)

        job = orchestrator.create_job(repo, topic, fmt, lang or cfg.project.language)
        console.print(f"[bold]Created job {job.id}[/bold]; running pipeline...")
        job = orchestrator.run_job(job.id, cfg, secrets, repo, dry_run=dry_run)
        console.print(f"[bold green]Job {job.id} -> {job.status.value}[/bold green]")
    except EdutubeError as e:
        _fail(e)


@app.command()
def resume(job_id: str, from_stage: str | None = typer.Option(None, "--from-stage")) -> None:
    try:
        cfg, secrets, repo = _load()
        job = orchestrator.resume(job_id, cfg, secrets, repo, from_stage=from_stage)
        console.print(f"[bold green]Job {job.id} -> {job.status.value}[/bold green]")
    except EdutubeError as e:
        _fail(e)


@app.command()
def status(
    job_id: str | None = typer.Argument(None), status_filter: str | None = typer.Option(None, "--status")
) -> None:
    try:
        _cfg, _secrets, repo = _load()
        if job_id:
            job = repo.get_job(job_id)
            console.print(
                f"[bold]{job.id}[/bold] format={job.format.value} status={job.status.value} "
                f"needs_human_review={job.needs_human_review}"
            )
            if job.last_error:
                console.print(f"[red]last_error: {job.last_error}[/red]")
            table = Table(title="Stage history")
            for col in ("stage", "status", "started_at", "duration_s", "error"):
                table.add_column(col)
            for row in repo.list_stage_runs(job_id):
                table.add_row(
                    row["stage"], row["status"], row["started_at"], str(row["duration_s"]), row["error"] or ""
                )
            console.print(table)
        else:
            status_enum = JobStatus(status_filter) if status_filter else None
            table = Table(title="Jobs")
            for col in ("id", "format", "status", "created_at"):
                table.add_column(col)
            for j in repo.list_jobs(status_enum):
                table.add_row(j.id, j.format.value, j.status.value, str(j.created_at))
            console.print(table)
    except EdutubeError as e:
        _fail(e)


@app.command(name="edit-script")
def edit_script(job_id: str) -> None:
    import os
    import subprocess

    try:
        cfg, _secrets, repo = _load()
        job = repo.get_job(job_id)
        path = cfg.resolve(cfg.paths.workspace) / "jobs" / job.id / "script.json"
        backup = path.with_suffix(".json.bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

        editor = os.environ.get("EDITOR")
        if shutil.which("code"):
            subprocess.run(["code", "--wait", str(path)], check=False)
        elif editor:
            subprocess.run([editor, str(path)], check=False)
        else:
            open_file(path)
            console.print("[yellow]Opened with the default app; re-run this command after saving to validate.[/yellow]")

        from edutube.content.script_writer import load_script

        try:
            load_script(path)
            console.print("[green]script.json is valid.[/green]")
        except Exception as e:  # noqa: BLE001
            path.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
            console.print(f"[bold red]Invalid script.json, restored previous version: {e}[/bold red]")
            raise typer.Exit(code=1) from e
    except EdutubeError as e:
        _fail(e)


@app.command()
def preview(job_id: str) -> None:
    try:
        cfg, _secrets, repo = _load()
        job = repo.get_job(job_id)
        path = cfg.resolve(cfg.paths.workspace) / "jobs" / job.id / "final.mp4"
        if not path.exists():
            console.print(f"[red]No final.mp4 for job {job_id} yet.[/red]")
            raise typer.Exit(code=1)
        open_file(path)
    except EdutubeError as e:
        _fail(e)


@app.command()
def approve(job_id: str) -> None:
    try:
        _cfg, _secrets, repo = _load()
        job = repo.get_job(job_id)
        if job.status != JobStatus.AWAITING_APPROVAL:
            console.print(f"[yellow]Job {job_id} is not AWAITING_APPROVAL (status={job.status.value})[/yellow]")
            raise typer.Exit(code=1)
        repo.update_job(job_id, status=JobStatus.APPROVED.value)
        console.print(f"[green]Job {job_id} approved.[/green]")
    except EdutubeError as e:
        _fail(e)


@app.command()
def reject(job_id: str, reason: str = typer.Option(..., "--reason")) -> None:
    try:
        _cfg, _secrets, repo = _load()
        repo.update_job(job_id, status=JobStatus.REJECTED.value, reject_reason=reason)
        console.print(f"[green]Job {job_id} rejected.[/green]")
    except EdutubeError as e:
        _fail(e)


# ---- upload / daily / quota / clean ------------------------------------------


@app.command()
def upload(job_id: str, dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    try:
        cfg, secrets, repo = _load()
        from edutube.pipeline.stages import UploadStage

        ctx = orchestrator.build_context(job_id, cfg, secrets, repo, dry_run=dry_run)
        if ctx.repo.get_upload(job_id) is not None and not dry_run:
            console.print(f"[yellow]Job {job_id} already uploaded.[/yellow]")
            return
        UploadStage().run(ctx)
        if not dry_run:
            console.print(f"[bold green]Job {job_id} uploaded.[/bold green]")
    except EdutubeError as e:
        _fail(e)


@app.command()
def daily(no_upload: bool = typer.Option(False, "--no-upload")) -> None:
    try:
        cfg, secrets, repo = _load()
        result = orchestrator.run_daily(cfg, secrets, repo, upload=not no_upload)
        console.print(f"[bold]created:[/bold] {result['created']}")
        console.print(f"[bold]failed:[/bold] {result['failed']}")
        console.print(f"[bold]uploaded:[/bold] {result['uploaded']}")
    except EdutubeError as e:
        _fail(e)


@app.command()
def quota() -> None:
    try:
        cfg, _secrets, repo = _load()
        from edutube.publish.quota import QuotaTracker

        tracker = QuotaTracker(repo, cfg.quota)
        used = tracker.used()
        console.print(f"Used today: {used} / {cfg.quota.daily_budget} units (margin {cfg.quota.safety_margin})")
        console.print(f"Remaining spendable: {tracker.remaining()} units")
        uploads_left = tracker.remaining() // cfg.quota.costs.videos_insert if cfg.quota.costs.videos_insert else 0
        console.print(f"Approx. uploads remaining today: {uploads_left}")
    except EdutubeError as e:
        _fail(e)


@app.command()
def clean(older_than: int = typer.Option(14, "--older-than")) -> None:
    import time

    try:
        cfg, _secrets, repo = _load()
        jobs_dir = cfg.resolve(cfg.paths.workspace) / "jobs"
        if not jobs_dir.exists():
            return
        cutoff = time.time() - older_than * 86400
        cleaned = 0
        for job_dir in jobs_dir.iterdir():
            if not job_dir.is_dir():
                continue
            if job_dir.stat().st_mtime >= cutoff:
                continue
            for sub in ("audio", "slides", "clips", "llm", "broll"):
                shutil.rmtree(job_dir / sub, ignore_errors=True)
            for f in ("joined.mp4", "concat.txt"):
                (job_dir / f).unlink(missing_ok=True)
            cleaned += 1
        console.print(f"[green]Cleaned working files for {cleaned} job(s) older than {older_than} days.[/green]")
    except EdutubeError as e:
        _fail(e)


@app.command()
def version() -> None:
    console.print(f"edutube-agent {__version__}")


if __name__ == "__main__":
    app()
