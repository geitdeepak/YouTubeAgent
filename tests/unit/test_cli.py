from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from edutube.cli import app

runner = CliRunner()


def test_init_creates_project_structure(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    result = runner.invoke(app, ["--config", str(config_path), "init"])
    assert result.exit_code == 0, result.output
    assert config_path.exists()
    for d in ("data", "secrets", "workspace", "logs", "assets/fonts"):
        assert (tmp_path / d).exists()


def test_init_does_not_overwrite_existing_config(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    runner.invoke(app, ["--config", str(config_path), "init"])
    config_path.write_text("project:\n  channel_name: Custom\n", encoding="utf-8")
    runner.invoke(app, ["--config", str(config_path), "init"])
    assert "Custom" in config_path.read_text(encoding="utf-8")


def test_topic_add_and_list(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    runner.invoke(app, ["--config", str(config_path), "init"])
    result = runner.invoke(
        app, ["--config", str(config_path), "topic", "add", "What is a Neural Network?", "--skip-check"]
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["--config", str(config_path), "topic", "list"], env={"COLUMNS": "200"})
    output = result.output.replace("\n", "")
    assert "What is a Neural" in output and "Network?" in output


def test_topic_import(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    runner.invoke(app, ["--config", str(config_path), "init"])
    csv_path = tmp_path / "topics.csv"
    csv_path.write_text(
        "title,format,level,priority,keywords,source_notes\n"
        "What is Artificial Intelligence?,both,beginner,5,ai,\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["--config", str(config_path), "topic", "import", "--file", str(csv_path)])
    assert result.exit_code == 0, result.output
    assert "Imported 1" in result.output


def test_status_empty(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    runner.invoke(app, ["--config", str(config_path), "init"])
    result = runner.invoke(app, ["--config", str(config_path), "status"])
    assert result.exit_code == 0, result.output


def test_doctor_runs_and_reports(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    runner.invoke(app, ["--config", str(config_path), "init"])
    result = runner.invoke(app, ["--config", str(config_path), "doctor"])
    assert "Check" in result.output


def test_generate_requires_format():
    result = runner.invoke(app, ["generate", "--next"])
    assert result.exit_code != 0
