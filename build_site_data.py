#!/usr/bin/env python3
"""
Build a combined data file for the local bracket visualizer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
FINAL_OUTPUT_DIR = ROOT / "final_output"
SITE_DATA_DIR = ROOT / "site_data"
SITE_DATA_FILE = SITE_DATA_DIR / "brackets.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def field_key(year: int, gender: str) -> str:
    return f"{year}-{gender}"


def infer_group_name(path: Path, brackets: list[dict[str, Any]]) -> str:
    stem = path.stem
    if stem.startswith("brackets-gpt-"):
        return "GPT"
    if stem.startswith("brackets-heuristic-"):
        parts = stem.split("-")
        if len(parts) >= 6:
            tag_parts = parts[4:-1]
            if tag_parts:
                return " ".join(tag_parts).replace("_", " ").title()
        return "Heuristic"

    generator = brackets[0].get("generator")
    if generator == "gpt":
        return "GPT"
    if generator == "heuristic":
        return "Heuristic"
    return path.name


def load_fields() -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for path in sorted(ROOT.glob("field-*-*.json")):
        data = load_json(path)
        year = data.get("year")
        gender = data.get("gender")
        if isinstance(year, int) and isinstance(gender, str):
            fields[field_key(year, gender)] = data
    return fields


def normalize_bracket(
    bracket: dict[str, Any],
    *,
    file_name: str,
    bracket_index: int,
) -> dict[str, Any]:
    return {
        "id": f"{file_name}::bracket-{bracket_index}",
        "file_name": file_name,
        "index": bracket_index,
        "title": bracket.get("title") or f"Bracket {bracket_index}",
        "generator": bracket.get("generator", "unknown"),
        "year": bracket.get("year"),
        "gender": bracket.get("gender"),
        "champion": bracket.get("champion"),
        "runner_up": bracket.get("runner_up"),
        "final_four": bracket.get("final_four", []),
        "summary": bracket.get("summary", ""),
        "regions": bracket.get("regions", {}),
        "raw": bracket,
    }


def build_payload() -> dict[str, Any]:
    fields = load_fields()
    files: list[dict[str, Any]] = []

    for path in sorted(FINAL_OUTPUT_DIR.glob("*.json")):
        data = load_json(path)
        if not isinstance(data, list):
            continue
        brackets = [
            normalize_bracket(item, file_name=path.name, bracket_index=index + 1)
            for index, item in enumerate(data)
            if isinstance(item, dict)
        ]
        if not brackets:
            continue

        first = brackets[0]
        group_name = infer_group_name(path, brackets)
        files.append(
            {
                "file_name": path.name,
                "group_name": group_name,
                "path": str(path),
                "year": first.get("year"),
                "gender": first.get("gender"),
                "generator": first.get("generator"),
                "count": len(brackets),
                "field_key": field_key(first["year"], first["gender"]),
                "brackets": brackets,
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "files": files,
        "fields": fields,
    }


def main() -> int:
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    SITE_DATA_FILE.write_text(json.dumps(build_payload(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {SITE_DATA_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
