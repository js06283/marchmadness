#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count championship picks across bracket JSON files."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default="final_output",
        help="Directory containing bracket JSON files. Defaults to final_output.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of champion rows to print per section.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_champions(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        return []

    champions: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        champion = item.get("champion")
        if isinstance(champion, str) and champion.strip():
            champions.append(champion.strip())
    return champions


def print_counter(title: str, counts: Counter[str], *, top: int) -> None:
    total = sum(counts.values())
    print(title)
    print(f"total_brackets={total}")
    for team, count in counts.most_common(top):
        pct = (count / total * 100) if total else 0.0
        print(f"{team}: {count} ({pct:.1f}%)")
    print()


def run() -> int:
    args = parse_args()
    base_dir = Path(args.directory)
    if not base_dir.exists():
        raise SystemExit(f"Directory not found: {base_dir}")

    files = sorted(base_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"No JSON files found in: {base_dir}")

    overall = Counter()

    for path in files:
        champions = extract_champions(load_json(path))
        if not champions:
            continue
        counts = Counter(champions)
        overall.update(counts)
        print_counter(f"[{path.name}]", counts, top=args.top)

    print_counter("[overall]", overall, top=args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
