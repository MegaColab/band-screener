"""Guard: no personal data may be committed to this public repository."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
ALLOWED_DOMAINS = ("users.noreply.github.com",)  # GitHub's anonymous commit address
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "demo_out", ".venv", "venv"}
TEXT_SUFFIXES = {".py", ".md", ".toml", ".txt", ".yml", ".yaml", ".json", ".csv", ".html", ".j2", ".ini", ".cfg", ""}


def repo_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not (set(path.relative_to(ROOT).parts) & SKIP_DIRS) and path.suffix in TEXT_SUFFIXES:
            yield path


def test_no_email_addresses_anywhere_in_the_repo():
    offenders = []
    for path in repo_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in EMAIL.findall(text):
            if not match.endswith(ALLOWED_DOMAINS):
                offenders.append(f"{path.relative_to(ROOT)}: {match}")
    assert not offenders, offenders
