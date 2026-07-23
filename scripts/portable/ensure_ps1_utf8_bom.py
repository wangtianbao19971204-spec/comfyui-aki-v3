"""Ensure portable updater scripts use UTF-8 BOM for Windows PowerShell 5.1."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PORTABLE_PS1 = list((REPO / "scripts" / "portable").glob("*.ps1"))


def ensure_utf8_bom(path: Path) -> None:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return
    text = raw.decode("utf-8")
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))


def test_portable_updater_ps1_files_have_utf8_bom() -> None:
    assert PORTABLE_PS1, "expected scripts/portable/*.ps1"
    for path in PORTABLE_PS1:
        data = path.read_bytes()
        assert data.startswith(b"\xef\xbb\xbf"), f"{path.name} must start with UTF-8 BOM for PS 5.1"


if __name__ == "__main__":
    for path in PORTABLE_PS1:
        ensure_utf8_bom(path)
        print("bom", path.name)
