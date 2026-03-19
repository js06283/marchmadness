#!/usr/bin/env python3
"""
Generate March Madness brackets with the OpenAI Responses API.

Cost control strategy:
1. Make a single web-search-enabled research call for the current tournament.
2. Reuse that research summary to generate one or many brackets without web search.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


API_URL = "https://api.openai.com/v1/responses"
DEFAULT_RESEARCH_MODEL = "gpt-5-mini"
DEFAULT_BRACKET_MODEL = "gpt-5-mini"
MODEL_PRICING = {
    "gpt-5-mini": {
        "input_per_million": 0.25,
        "cached_input_per_million": 0.025,
        "output_per_million": 2.00,
    }
}
WEB_SEARCH_PRICE_PER_CALL = 0.01
ROUND_NAMES = ["round_of_64", "round_of_32", "sweet_16", "elite_8"]
ROUND_LABELS = {
    "round_of_64": "Round of 64",
    "round_of_32": "Round of 32",
    "sweet_16": "Sweet 16",
    "elite_8": "Elite 8",
    "final_four": "Final Four",
    "championship": "National Championship",
}
ROUND_THRESHOLD_DEFAULTS = {
    "round_of_64": 8,
    "round_of_32": 5,
    "sweet_16": 3,
    "elite_8": 2,
    "final_four": 2,
    "championship": 1,
}
THRESHOLD_FAVORITE_PROBABILITIES = {
    1: 0.68,
    2: 0.74,
    3: 0.80,
    4: 0.85,
    5: 0.89,
    6: 0.92,
    7: 0.945,
    8: 0.96,
    9: 0.97,
    10: 0.978,
    11: 0.984,
    12: 0.989,
    13: 0.992,
    14: 0.995,
    15: 0.997,
}
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate March Madness brackets with one web-research pass."
    )
    parser.add_argument("--year", type=int, default=dt.date.today().year)
    parser.add_argument("--gender", choices=["mens", "womens"], default="mens")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--outdir", default="final_output")
    parser.add_argument(
        "--output-tag",
        default="",
        help="Optional short tag appended to output filenames.",
    )
    parser.add_argument(
        "--generator",
        choices=["gpt", "heuristic", "both"],
        default="gpt",
        help="Choose GPT generation, heuristic simulation, or both.",
    )
    parser.add_argument("--research-model", default=DEFAULT_RESEARCH_MODEL)
    parser.add_argument("--bracket-model", default=DEFAULT_BRACKET_MODEL)
    parser.add_argument(
        "--gpt-workers",
        type=int,
        default=4,
        help="Maximum number of concurrent GPT bracket generation calls.",
    )
    parser.add_argument(
        "--field-file",
        help="Optional JSON file with official seeds, regions, and first-round matchups.",
    )
    parser.add_argument(
        "--skip-research",
        action="store_true",
        help="Reuse an existing research file instead of calling web search again.",
    )
    parser.add_argument(
        "--research-file",
        help="Path to a saved research JSON file. Required with --skip-research.",
    )
    parser.add_argument(
        "--max-tool-calls",
        type=int,
        default=3,
        help="Upper bound for web search tool calls during the research pass.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for heuristic simulation.",
    )
    parser.add_argument(
        "--favorite-threshold-round64",
        type=int,
        default=ROUND_THRESHOLD_DEFAULTS["round_of_64"],
        help="If seed difference is at least this value in the Round of 64, auto-pick the favorite.",
    )
    parser.add_argument(
        "--favorite-threshold-round32",
        type=int,
        default=ROUND_THRESHOLD_DEFAULTS["round_of_32"],
        help="If seed difference is at least this value in the Round of 32, auto-pick the favorite.",
    )
    parser.add_argument(
        "--favorite-threshold-sweet16",
        type=int,
        default=ROUND_THRESHOLD_DEFAULTS["sweet_16"],
        help="If seed difference is at least this value in the Sweet 16, auto-pick the favorite.",
    )
    parser.add_argument(
        "--favorite-threshold-elite8",
        type=int,
        default=ROUND_THRESHOLD_DEFAULTS["elite_8"],
        help="If seed difference is at least this value in the Elite 8, auto-pick the favorite.",
    )
    parser.add_argument(
        "--favorite-threshold-final4",
        type=int,
        default=ROUND_THRESHOLD_DEFAULTS["final_four"],
        help="If seed difference is at least this value in the Final Four, auto-pick the favorite.",
    )
    parser.add_argument(
        "--favorite-threshold-title",
        type=int,
        default=ROUND_THRESHOLD_DEFAULTS["championship"],
        help="If seed difference is at least this value in the title game, auto-pick the favorite.",
    )
    return parser.parse_args()


def maybe_get_api_key(required: bool) -> str | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if required and not api_key:
        raise SystemExit("OPENAI_API_KEY is not set.")
    return api_key


def build_payload(
    model: str,
    prompt: str,
    *,
    tools: list[dict[str, Any]] | None = None,
    max_output_tokens: int = 4000,
    max_tool_calls: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
    }

    if model.startswith("gpt-5") or model.startswith("o"):
        payload["reasoning"] = {"effort": "low"}

    if tools:
        payload["tools"] = tools
        if max_tool_calls is not None:
            payload["max_tool_calls"] = max_tool_calls

    return payload


def call_responses_api(api_key: str, payload: dict[str, Any], *, retries: int = 4) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(retries):
        request = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            retriable = exc.code in {408, 429, 500, 502, 503, 504}
            if not retriable or attempt == retries - 1:
                raise RuntimeError(f"OpenAI API error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            if attempt == retries - 1:
                raise RuntimeError(f"Network error talking to OpenAI: {exc}") from exc

        time.sleep(2 ** attempt)

    raise RuntimeError("OpenAI API call failed after retries.")


def extract_output_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if text:
                    chunks.append(text)

    if chunks:
        return "\n".join(chunks).strip()

    if isinstance(response.get("output_text"), str):
        return response["output_text"].strip()

    raise RuntimeError("No text output found in API response.")


def parse_json_loose(text: str) -> Any:
    cleaned = text.strip()

    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(cleaned[start : end + 1])

    raise RuntimeError("Model output was not valid JSON.")


def research_prompt(year: int, gender: str) -> str:
    tournament = "men's" if gender == "mens" else "women's"
    return f"""
You are building a March Madness bracket generator for the {year} NCAA {tournament} tournament.

Use web search to gather only the information needed to build brackets well:
- official bracket field and region placement
- seeds and first-round matchups
- injuries, suspensions, or absences that materially affect games
- team strength indicators that matter in tournament play
- public-pick or overhype spots worth fading if evidence supports it

Return JSON only with this shape:
{{
  "year": {year},
  "gender": "{gender}",
  "generated_at": "ISO-8601 timestamp",
  "regions": {{
    "East": [{{"seed": 1, "team": "Team", "matchup_seed": 16}}],
    "West": [],
    "South": [],
    "Midwest": []
  }},
  "team_notes": [
    {{
      "team": "Team",
      "seed": 1,
      "region": "East",
      "summary": "short note",
      "confidence": "low|medium|high"
    }}
  ],
  "macro_notes": [
    "short note"
  ],
  "sources": [
    {{
      "label": "short source name",
      "url": "https://..."
    }}
  ]
}}

Requirements:
- Keep team_notes concise but useful.
- Include all 16 seeded slots for each region if the field is available.
- If a play-in team is not finalized, include the known placeholder.
- Use source URLs from reputable reporting or official pages.
- Do not include markdown fences.
""".strip()


def research_prompt_with_field(year: int, gender: str, field: dict[str, Any]) -> str:
    tournament = "men's" if gender == "mens" else "women's"
    field_blob = json.dumps(field, indent=2)
    return f"""
You are building a March Madness bracket generator for the {year} NCAA {tournament} tournament.

The official tournament field is provided below. Do not search for teams, regions, seeds, or first-round pairings.
Use web search only for volatile context that helps with picks:
- injuries, suspensions, or absences
- late-season form and matchup-specific strengths
- coaching or roster context relevant to tournament games
- public-pick consensus or overhyped teams worth fading if evidence supports it

Official field:
{field_blob}

Return JSON only with this shape:
{{
  "year": {year},
  "gender": "{gender}",
  "generated_at": "ISO-8601 timestamp",
  "regions": {{
    "East": [{{"seed": 1, "team": "Team", "matchup_seed": 16, "opponent": "Opponent"}}],
    "West": [],
    "South": [],
    "Midwest": []
  }},
  "team_notes": [
    {{
      "team": "Team",
      "seed": 1,
      "region": "East",
      "summary": "short note",
      "confidence": "low|medium|high"
    }}
  ],
  "macro_notes": [
    "short note"
  ],
  "sources": [
    {{
      "label": "short source name",
      "url": "https://..."
    }}
  ]
}}

Requirements:
- Preserve the provided field exactly in the regions output.
- Keep team_notes concise but useful.
- Use source URLs from reputable reporting or official pages.
- Do not include markdown fences.
""".strip()


def bracket_prompt(
    year: int,
    gender: str,
    bracket_index: int,
    research: dict[str, Any],
    previous_error: str | None = None,
) -> str:
    tournament = "men's" if gender == "mens" else "women's"
    research_blob = json.dumps(research, indent=2)
    retry_guidance = ""
    if previous_error:
        retry_guidance = f"""

The previous attempt was invalid. Fix this specific issue and regenerate the full bracket:
- {previous_error}
""".rstrip()
    return f"""
You are generating bracket #{bracket_index} for the {year} NCAA {tournament} tournament.

Use the tournament research below. Do not invent teams outside the provided field.
Prefer concise reasoning and make sure every game has a winner.
Generate a complete bracket based on your best judgment from the provided information.{retry_guidance}

Research:
{research_blob}

Return JSON only with this exact top-level shape:
{{
  "year": {year},
  "gender": "{gender}",
  "champion": "Team",
  "runner_up": "Team",
  "final_four": ["Team", "Team", "Team", "Team"],
  "regions": {{
    "East": {{
      "round_of_64": [{{"matchup": "1 Team A vs 16 Team B", "winner": "Team A", "reason": "short reason"}}],
      "round_of_32": [],
      "sweet_16": [],
      "elite_8": []
    }},
    "West": {{"round_of_64": [], "round_of_32": [], "sweet_16": [], "elite_8": []}},
    "South": {{"round_of_64": [], "round_of_32": [], "sweet_16": [], "elite_8": []}},
    "Midwest": {{"round_of_64": [], "round_of_32": [], "sweet_16": [], "elite_8": []}}
  }},
  "title": "short human-friendly label",
  "summary": "2-3 sentence explanation of the bracket's logic"
}}

Rules:
- Each region must have 8 round_of_64 picks, 4 round_of_32 picks, 2 sweet_16 picks, and 1 elite_8 pick.
- final_four must contain the 4 Elite Eight winners.
- champion and runner_up must be consistent with the Final Four winners.
- Reasons must be short and tied to the provided research.
- Do not include markdown fences.
""".strip()


def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def timestamp_slug() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def tagged_filename(prefix: str, *, year: int, gender: str, output_tag: str) -> str:
    base = f"{prefix}-{year}-{gender}"
    if output_tag:
        base += f"-{output_tag}"
    return f"{base}-{timestamp_slug()}.json"


def validate_bracket(bracket: dict[str, Any]) -> None:
    expected_round_sizes = {
        "round_of_64": 8,
        "round_of_32": 4,
        "sweet_16": 2,
        "elite_8": 1,
    }

    regions = bracket.get("regions", {})
    for region_name in ["East", "West", "South", "Midwest"]:
        region = regions.get(region_name)
        if not isinstance(region, dict):
            raise RuntimeError(f"Bracket missing region: {region_name}")

        for round_name, expected_size in expected_round_sizes.items():
            picks = region.get(round_name)
            if not isinstance(picks, list) or len(picks) != expected_size:
                raise RuntimeError(
                    f"Bracket region {region_name} has invalid {round_name} size: "
                    f"expected {expected_size}"
                )

    final_four = bracket.get("final_four")
    if not isinstance(final_four, list) or len(final_four) != 4:
        raise RuntimeError("Bracket final_four must contain 4 teams.")


def normalize_gpt_bracket(
    bracket: dict[str, Any],
    *,
    year: int,
    gender: str,
    bracket_index: int,
) -> dict[str, Any]:
    bracket["year"] = year
    bracket["gender"] = gender
    if not bracket.get("title"):
        bracket["title"] = f"GPT bracket {bracket_index}"
    if "strategy" in bracket:
        bracket.pop("strategy", None)
    return bracket


def validate_field(field: dict[str, Any]) -> None:
    regions = field.get("regions")
    if not isinstance(regions, dict):
        raise RuntimeError("Field file must contain a regions object.")

    for region_name in ["East", "West", "South", "Midwest"]:
        games = regions.get(region_name)
        if not isinstance(games, list) or len(games) != 8:
            raise RuntimeError(f"Field region {region_name} must contain 8 first-round games.")

        for game in games:
            if not isinstance(game, dict):
                raise RuntimeError(f"Field region {region_name} contains an invalid game entry.")
            for key in ["seed", "team", "matchup_seed", "opponent"]:
                if key not in game:
                    raise RuntimeError(f"Field region {region_name} is missing key: {key}")


def get_usage(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage") or {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    input_details = usage.get("input_tokens_details") or {}
    cached_input_tokens = int(input_details.get("cached_tokens", 0) or 0)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "uncached_input_tokens": max(input_tokens - cached_input_tokens, 0),
        "output_tokens": output_tokens,
    }


def count_web_search_calls(response: dict[str, Any]) -> int:
    count = 0
    for item in response.get("output", []):
        if item.get("type") == "web_search_call":
            count += 1
    return count


def estimate_cost(model: str, usage: dict[str, int], *, web_search_calls: int = 0) -> float | None:
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        return None

    input_cost = (
        usage["uncached_input_tokens"] / 1_000_000
    ) * pricing["input_per_million"]
    cached_input_cost = (
        usage["cached_input_tokens"] / 1_000_000
    ) * pricing["cached_input_per_million"]
    output_cost = (usage["output_tokens"] / 1_000_000) * pricing["output_per_million"]
    web_search_cost = web_search_calls * WEB_SEARCH_PRICE_PER_CALL
    return input_cost + cached_input_cost + output_cost + web_search_cost


def print_cost_line(label: str, model: str, usage: dict[str, int], cost: float | None, *, web_search_calls: int = 0) -> None:
    parts = [
        f"{label}: model={model}",
        f"input={usage['input_tokens']}",
        f"cached_input={usage['cached_input_tokens']}",
        f"output={usage['output_tokens']}",
    ]
    if web_search_calls:
        parts.append(f"web_search_calls={web_search_calls}")
    if cost is None:
        parts.append("estimated_cost=unknown")
    else:
        parts.append(f"estimated_cost=${cost:.4f}")
    print(" | ".join(parts))


def fetch_research(
    *,
    api_key: str,
    year: int,
    gender: str,
    research_model: str,
    max_tool_calls: int,
    field: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, int], int, float | None, str | None]:
    if field is not None:
        prompt = research_prompt_with_field(year, gender, field)
    else:
        prompt = research_prompt(year, gender)

    research_payload = build_payload(
        research_model,
        prompt,
        tools=[{"type": "web_search"}],
        max_output_tokens=5000,
        max_tool_calls=max_tool_calls,
    )
    research_response = call_responses_api(api_key, research_payload)
    research_text = extract_output_text(research_response)
    research = parse_json_loose(research_text)
    research_usage = get_usage(research_response)
    research_web_search_calls = count_web_search_calls(research_response)
    research_cost = estimate_cost(
        research_model,
        research_usage,
        web_search_calls=research_web_search_calls,
    )
    if field is not None:
        research["regions"] = field["regions"]
        if "first_four" in field:
            research["first_four"] = field["first_four"]
    response_id = research_response.get("id")
    research["api_meta"] = {
        "research_model": research_model,
        "response_id": response_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return research, research_usage, research_web_search_calls, research_cost, response_id


def build_thresholds(args: argparse.Namespace) -> dict[str, int]:
    return {
        "round_of_64": args.favorite_threshold_round64,
        "round_of_32": args.favorite_threshold_round32,
        "sweet_16": args.favorite_threshold_sweet16,
        "elite_8": args.favorite_threshold_elite8,
        "final_four": args.favorite_threshold_final4,
        "championship": args.favorite_threshold_title,
    }


def base_favorite_probability(seed_a: int, seed_b: int) -> float:
    diff = abs(seed_a - seed_b)
    probs = {
        0: 0.50,
        1: 0.57,
        2: 0.64,
        3: 0.70,
        4: 0.76,
        5: 0.81,
        6: 0.85,
        7: 0.89,
        8: 0.92,
        9: 0.94,
        10: 0.955,
        11: 0.965,
        12: 0.975,
        13: 0.982,
        14: 0.988,
        15: 0.993,
    }
    return probs.get(min(diff, 15), 0.993)


def threshold_adjusted_probability(diff: int, threshold: int) -> float:
    threshold_floor = THRESHOLD_FAVORITE_PROBABILITIES.get(
        min(threshold, 15), 0.96
    )
    gap_bonus = max(diff - threshold, 0) * 0.008
    return min(threshold_floor + gap_bonus, 0.997)


def make_team(seed: int, team: str, region: str) -> dict[str, Any]:
    return {"seed": seed, "team": team, "region": region}


def format_matchup(team_a: dict[str, Any], team_b: dict[str, Any]) -> str:
    return f"{team_a['seed']} {team_a['team']} vs {team_b['seed']} {team_b['team']}"


def simulate_game(
    team_a: dict[str, Any],
    team_b: dict[str, Any],
    *,
    round_name: str,
    rng: random.Random,
    thresholds: dict[str, int],
) -> tuple[dict[str, Any], str]:
    if team_a["seed"] <= team_b["seed"]:
        favorite = team_a
        underdog = team_b
    else:
        favorite = team_b
        underdog = team_a

    diff = abs(team_a["seed"] - team_b["seed"])
    threshold = thresholds[round_name]
    favorite_prob = base_favorite_probability(team_a["seed"], team_b["seed"])
    if diff >= threshold:
        favorite_prob = max(favorite_prob, threshold_adjusted_probability(diff, threshold))
    favorite_prob = min(max(favorite_prob, 0.05), 0.997)
    favorite_wins = rng.random() < favorite_prob
    winner = favorite if favorite_wins else underdog
    reason = (
        f"Simulated {ROUND_LABELS[round_name].lower()}: favorite win prob "
        f"{favorite_prob:.2f}; picked {winner['team']}."
    )
    if diff >= threshold:
        reason = (
            f"Threshold-biased simulation with seed gap {diff} >= {threshold}: "
            f"favorite win prob {favorite_prob:.2f}; picked {winner['team']}."
        )
    return winner, reason


def simulate_region(
    region_name: str,
    games: list[dict[str, Any]],
    *,
    rng: random.Random,
    thresholds: dict[str, int],
) -> tuple[dict[str, list[dict[str, str]]], dict[str, Any]]:
    rounds: dict[str, list[dict[str, str]]] = {
        "round_of_64": [],
        "round_of_32": [],
        "sweet_16": [],
        "elite_8": [],
    }

    current = [
        (
            make_team(game["seed"], game["team"], region_name),
            make_team(game["matchup_seed"], game["opponent"], region_name),
        )
        for game in games
    ]

    for round_name in ROUND_NAMES:
        winners: list[dict[str, Any]] = []
        for team_a, team_b in current:
            winner, reason = simulate_game(
                team_a,
                team_b,
                round_name=round_name,
                rng=rng,
                thresholds=thresholds,
            )
            rounds[round_name].append(
                {
                    "matchup": format_matchup(team_a, team_b),
                    "winner": winner["team"],
                    "reason": reason,
                }
            )
            winners.append(winner)

        if round_name != "elite_8":
            current = [(winners[i], winners[i + 1]) for i in range(0, len(winners), 2)]
        else:
            current = []

    regional_champion_name = rounds["elite_8"][0]["winner"]
    regional_champion = next(
        team for team in winners if team["team"] == regional_champion_name
    )
    return rounds, regional_champion


def generate_heuristic_bracket(
    field: dict[str, Any],
    *,
    year: int,
    gender: str,
    bracket_index: int,
    rng: random.Random,
    thresholds: dict[str, int],
    output_tag: str,
    seed_value: int,
) -> dict[str, Any]:
    regions: dict[str, Any] = {}
    regional_champions: list[dict[str, Any]] = []

    for region_name in ["East", "West", "South", "Midwest"]:
        region_rounds, champion = simulate_region(
            region_name,
            field["regions"][region_name],
            rng=rng,
            thresholds=thresholds,
        )
        regions[region_name] = region_rounds
        regional_champions.append(champion)

    semifinal_pairs = [
        (regional_champions[0], regional_champions[1]),
        (regional_champions[2], regional_champions[3]),
    ]
    final_four_winners: list[dict[str, Any]] = []
    semifinal_reasons: list[str] = []
    for team_a, team_b in semifinal_pairs:
        winner, reason = simulate_game(
            team_a,
            team_b,
            round_name="final_four",
            rng=rng,
            thresholds=thresholds,
        )
        final_four_winners.append(winner)
        semifinal_reasons.append(reason)

    champion, title_reason = simulate_game(
        final_four_winners[0],
        final_four_winners[1],
        round_name="championship",
        rng=rng,
        thresholds=thresholds,
    )
    runner_up = (
        final_four_winners[1]
        if champion["team"] == final_four_winners[0]["team"]
        else final_four_winners[0]
    )

    summary = (
        f"Heuristic simulation using threshold policy {thresholds} and seed-based "
        f"win probabilities. "
        f"Final Four decisions: {semifinal_reasons[0]} {semifinal_reasons[1]} "
        f"Title game: {title_reason}"
    )
    title = f"Heuristic bracket {bracket_index}"
    if output_tag:
        title = f"Heuristic {output_tag} bracket {bracket_index}"

    bracket = {
        "year": year,
        "gender": gender,
        "strategy": "heuristic-thresholds",
        "champion": champion["team"],
        "runner_up": runner_up["team"],
        "final_four": [team["team"] for team in regional_champions],
        "regions": regions,
        "title": title,
        "summary": summary,
        "generator": "heuristic",
        "heuristic_meta": {
            "bracket_index": bracket_index,
            "thresholds": thresholds,
            "seed": seed_value,
            "output_tag": output_tag or None,
        },
    }
    validate_bracket(bracket)
    return bracket


def generate_single_gpt_bracket(
    *,
    api_key: str,
    year: int,
    gender: str,
    bracket_index: int,
    bracket_model: str,
    research_model: str,
    max_tool_calls: int,
    field: dict[str, Any] | None = None,
    research: dict[str, Any] | None = None,
    max_attempts: int = 3,
) -> tuple[
    int,
    dict[str, Any],
    dict[str, int],
    float | None,
    dict[str, int] | None,
    int,
    float | None,
]:
    total_usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "output_tokens": 0,
    }
    total_cost = 0.0
    have_cost = True
    previous_error: str | None = None
    bracket_research = research
    research_usage: dict[str, int] | None = None
    research_web_search_calls = 0
    research_cost: float | None = None

    if bracket_research is None:
        (
            bracket_research,
            research_usage,
            research_web_search_calls,
            research_cost,
            _,
        ) = fetch_research(
            api_key=api_key,
            year=year,
            gender=gender,
            research_model=research_model,
            max_tool_calls=max_tool_calls,
            field=field,
        )

    for attempt in range(1, max_attempts + 1):
        payload = build_payload(
            bracket_model,
            bracket_prompt(
                year,
                gender,
                bracket_index,
                bracket_research,
                previous_error=previous_error,
            ),
            max_output_tokens=7000,
        )
        response = call_responses_api(api_key, payload)
        usage = get_usage(response)
        for key, value in usage.items():
            total_usage[key] += value
        attempt_cost = estimate_cost(bracket_model, usage)
        if attempt_cost is None:
            have_cost = False
        else:
            total_cost += attempt_cost

        try:
            bracket_text = extract_output_text(response)
            bracket = parse_json_loose(bracket_text)
            bracket = normalize_gpt_bracket(
                bracket,
                year=year,
                gender=gender,
                bracket_index=bracket_index,
            )
            validate_bracket(bracket)
            bracket["api_meta"] = {
                "bracket_model": bracket_model,
                "response_id": response.get("id"),
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "attempts": attempt,
                "research_model": bracket_research.get("api_meta", {}).get("research_model"),
                "research_response_id": bracket_research.get("api_meta", {}).get("response_id"),
            }
            bracket["generator"] = "gpt"
            return (
                bracket_index,
                bracket,
                total_usage,
                total_cost if have_cost else None,
                research_usage,
                research_web_search_calls,
                research_cost,
            )
        except RuntimeError as exc:
            previous_error = str(exc)
            if attempt == max_attempts:
                raise RuntimeError(
                    f"GPT bracket {bracket_index} failed after {max_attempts} attempts: "
                    f"{previous_error}"
                ) from exc

    raise RuntimeError(f"GPT bracket {bracket_index} failed unexpectedly.")


def run() -> int:
    args = parse_args()
    needs_api = args.generator in {"gpt", "both"}
    api_key = maybe_get_api_key(needs_api)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    field: dict[str, Any] | None = None
    total_estimated_cost = 0.0
    have_total_cost = True
    thresholds = build_thresholds(args)
    rng = random.Random(args.seed)

    if args.field_file:
        field = load_json(Path(args.field_file))
        validate_field(field)

    shared_research: dict[str, Any] | None = None
    if args.generator in {"gpt", "both"}:
        if args.skip_research:
            if not args.research_file:
                raise SystemExit("--research-file is required with --skip-research.")
            shared_research = load_json(Path(args.research_file))

    gpt_brackets: list[dict[str, Any]] = []
    if args.generator in {"gpt", "both"}:
        max_workers = max(1, min(args.gpt_workers, args.count))
        futures: dict[concurrent.futures.Future, int] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for idx in range(args.count):
                bracket_index = idx + 1
                future = executor.submit(
                    generate_single_gpt_bracket,
                    api_key=api_key,
                    year=args.year,
                    gender=args.gender,
                    bracket_index=bracket_index,
                    bracket_model=args.bracket_model,
                    research_model=args.research_model,
                    max_tool_calls=args.max_tool_calls,
                    field=field,
                    research=shared_research,
                )
                futures[future] = bracket_index

            ordered_brackets: dict[int, dict[str, Any]] = {}
            failures: list[tuple[int, str]] = []
            for future in concurrent.futures.as_completed(futures):
                bracket_index = futures[future]
                try:
                    (
                        completed_index,
                        bracket,
                        usage,
                        bracket_cost,
                        research_usage,
                        research_web_search_calls,
                        per_bracket_research_cost,
                    ) = future.result()
                except Exception as exc:
                    failures.append((bracket_index, str(exc)))
                    print(f"GPT bracket {bracket_index}/{args.count} failed: {exc}")
                    continue
                if research_usage is not None:
                    print_cost_line(
                        f"GPT bracket {completed_index} research usage",
                        args.research_model,
                        research_usage,
                        per_bracket_research_cost,
                        web_search_calls=research_web_search_calls,
                    )
                    if per_bracket_research_cost is None:
                        have_total_cost = False
                    else:
                        total_estimated_cost += per_bracket_research_cost
                print_cost_line(
                    f"GPT bracket {completed_index} usage",
                    args.bracket_model,
                    usage,
                    bracket_cost,
                )
                if bracket_cost is None:
                    have_total_cost = False
                else:
                    total_estimated_cost += bracket_cost
                ordered_brackets[completed_index] = bracket
                print(
                    f"Generated GPT bracket {completed_index}/{args.count}: "
                    f"{bracket.get('title', f'GPT bracket {completed_index}')}"
                )

        gpt_brackets = [ordered_brackets[index] for index in range(1, args.count + 1) if index in ordered_brackets]

        if failures:
            print(f"Failed GPT brackets: {len(failures)}")
            for bracket_index, message in sorted(failures):
                print(f"  - bracket {bracket_index}: {message}")
        if not gpt_brackets:
            raise SystemExit("No GPT brackets were generated successfully.")

        gpt_file = outdir / tagged_filename(
            "brackets-gpt",
            year=args.year,
            gender=args.gender,
            output_tag=args.output_tag,
        )
        save_json(gpt_file, gpt_brackets)
        print(f"Saved GPT brackets: {gpt_file}")

    heuristic_brackets: list[dict[str, Any]] = []
    if args.generator in {"heuristic", "both"}:
        if field is None:
            raise SystemExit("--field-file is required for heuristic generation.")
        for idx in range(args.count):
            bracket = generate_heuristic_bracket(
                field,
                year=args.year,
                gender=args.gender,
                bracket_index=idx + 1,
                rng=rng,
                thresholds=thresholds,
                output_tag=args.output_tag,
                seed_value=args.seed,
            )
            heuristic_brackets.append(bracket)
            print(
                f"Generated heuristic bracket {idx + 1}/{args.count}: "
                f"{bracket.get('title', 'heuristic')}"
            )

        heuristic_file = outdir / tagged_filename(
            "brackets-heuristic",
            year=args.year,
            gender=args.gender,
            output_tag=args.output_tag,
        )
        save_json(heuristic_file, heuristic_brackets)
        print(f"Saved heuristic brackets: {heuristic_file}")

    if have_total_cost:
        print(f"Estimated total cost: ${total_estimated_cost:.4f}")
    else:
        print("Estimated total cost: unknown for one or more models.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        raise SystemExit(130)
