"""Shared release-file and LF-checkout rules for offline packaging."""
from __future__ import annotations

from pathlib import Path


HASH_EXCLUSIONS = frozenset({"manifest.json", "reports/validation/p0-validation.json"})
EXCLUDED_PARTS = frozenset({".git", "__pycache__", "staging"})
BINARY_SUFFIXES = frozenset({
    ".7z", ".avif", ".gif", ".gz", ".ico", ".jpeg", ".jpg", ".mp3", ".mp4",
    ".pdf", ".png", ".pyc", ".rar", ".tgz", ".webm", ".webp", ".woff", ".woff2", ".zip",
})


def is_release_file(path: Path) -> bool:
    return path.is_file() and not (set(path.parts) & EXCLUDED_PARTS) and path.suffix.lower() != ".pyc"


def release_files(root: Path) -> list[Path]:
    return [path for path in sorted(root.rglob("*")) if is_release_file(path)]


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() not in BINARY_SUFFIXES


def lf_violations(root: Path) -> list[str]:
    """Return release text files that cannot be hashed as LF checkout bytes."""
    violations = []
    for path in release_files(root):
        if is_text_file(path) and b"\r" in path.read_bytes():
            violations.append(path.relative_to(root).as_posix())
    return violations
