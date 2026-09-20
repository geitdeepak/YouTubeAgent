from __future__ import annotations

from pathlib import PureWindowsPath

from edutube.media.ffmpeg import ff_filter_path


def test_ff_filter_path_escapes_colon_and_backslash():
    p = PureWindowsPath(r"C:\agentcode\assets\fonts")
    escaped = ff_filter_path(p)  # type: ignore[arg-type]
    assert escaped == "C\\:/agentcode/assets/fonts"


def test_ff_filter_path_escapes_quote():
    from pathlib import Path

    escaped = ff_filter_path(Path("it's/a/path"))
    assert "\\'" in escaped
