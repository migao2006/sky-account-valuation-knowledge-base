#!/usr/bin/env python3
"""Refresh P0 account season profiles after the local canonical catalog changes."""
from __future__ import annotations
import argparse
import importlib.util
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline P0 migration/profile refresh")
    parser.add_argument("--v3-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--legacy-root", type=Path)
    args = parser.parse_args()
    migration = args.v3_root / "tools" / "migrate" / "migrate_v24_to_p0.py"
    spec = importlib.util.spec_from_file_location("p0_migration", migration)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load P0 migration module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print(module.migrate(args.v3_root.resolve(), (args.legacy_root or module.legacy_root(args.v3_root)).resolve()))


if __name__ == "__main__":
    main()
