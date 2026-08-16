#!/usr/bin/env python3
"""Create a deterministic offline P0 ZIP without caches or research staging."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
from release_files import HASH_EXCLUSIONS, lf_violations, release_files


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    residue = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.name == "__pycache__" or path.suffix == ".pyc" or (path.is_dir() and path.name == "staging")
    )
    if residue:
        raise RuntimeError(f"release root contains cache or staging residue: {residue}")
    files = release_files(root)
    violations = lf_violations(root)
    if violations:
        raise RuntimeError(f"release text files must use LF: {violations}")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    actual = {path.relative_to(root).as_posix() for path in files}
    declared = set(manifest.get("file_hashes", {})) | set(manifest.get("hash_exclusions", []))
    if set(manifest.get("hash_exclusions", [])) != HASH_EXCLUSIONS:
        raise RuntimeError("manifest hash exclusions must only contain generated self-references")
    if actual != declared:
        raise RuntimeError(f"release file set differs from manifest: extra={sorted(actual-declared)}, missing={sorted(declared-actual)}")
    hash_mismatches = [
        relative for relative, expected in manifest.get("file_hashes", {}).items()
        if not (root / relative).is_file() or digest(root / relative) != expected
    ]
    if hash_mismatches:
        raise RuntimeError(f"manifest hashes do not match release bytes: {hash_mismatches}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = Path(root.name) / path.relative_to(root)
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(2026, 8, 16, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    print(json.dumps({"output": str(output), "files": len(files), "bytes": output.stat().st_size, "sha256": digest(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
