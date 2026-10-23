"""CPU-only synthetic benchmark for NekoTrack's local recommendation ranking.

Run from the repository root:
    python experiments/benchmark_recommendations.py
    python experiments/benchmark_recommendations.py --candidate-sizes 50 250 1000 --sources 100 --iterations 9

This does not access the network, database, saved library, or user data. It reports
Python ranking time only; it is not an end-to-end app performance claim.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

# Permit running this file directly from the repository root without installing
# the project as a package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from recommendation_engine import rank_candidates  # noqa: E402


GENRES = ("Fantasy", "Drama", "Adventure", "Mystery", "Comedy", "Action", "Slice of Life")
TAGS = ("Time Travel", "Found Family", "Magic", "School", "Politics", "Revenge", "Coming of Age")


def build_sources(source_count: int, credits_per_source: int) -> dict:
    """Build repeatable contributor profiles, with overlapping IDs across works."""
    profile = {}
    for source_index in range(source_count):
        base_id = 10_000 + source_index * max(credits_per_source, 1)
        characters = [
            {"id": base_id + i, "role": ("MAIN", "SUPPORTING", "BACKGROUND")[i % 3],
             "name": {"full": f"Character {base_id + i}"}}
            for i in range(credits_per_source)
        ]
        voices = [
            {"id": 100_000 + ((base_id + i) % 800), "language": ("Japanese", "English")[i % 2],
             "character_role": ("MAIN", "SUPPORTING")[i % 2],
             "name": {"full": f"Voice Actor {(base_id + i) % 800}"}}
            for i in range(max(1, credits_per_source // 2))
        ]
        staff = [
            {"id": 200_000 + ((base_id + i) % 400),
             "role": ("Director", "Series Composition", "Music", "Producer")[i % 4],
             "name": {"full": f"Staff {(base_id + i) % 400}"}}
            for i in range(max(1, credits_per_source // 3))
        ]
        profile[source_index + 1] = {
            "_source_title": f"Saved source {source_index + 1}",
            "_source_weight": 1.0 + (source_index % 4) * 0.25,
            "characters": characters,
            "voice_actors": voices,
            "staff": staff,
        }
    return profile


def build_candidates(candidate_count: int, credits_per_candidate: int = 8) -> list[dict]:
    candidates = []
    for index in range(candidate_count):
        candidate_id = index + 1
        character_edges = []
        for offset in range(credits_per_candidate):
            entity_id = 10_000 + ((index * 7 + offset * 11) % 50_000)
            voices = [
                {"id": 100_000 + ((index * 13 + offset) % 800),
                 "language": ("Japanese", "English")[offset % 2],
                 "name": {"full": f"Voice Actor {(index * 13 + offset) % 800}"}}
            ]
            character_edges.append({
                "role": ("MAIN", "SUPPORTING", "BACKGROUND")[offset % 3],
                "node": {"id": entity_id, "name": {"full": f"Character {entity_id}"}},
                "voiceActors": voices,
            })
        staff_edges = [
            {"role": ("Director", "Series Composition", "Music")[offset % 3],
             "node": {"id": 200_000 + ((index * 5 + offset) % 400),
                      "name": {"full": f"Staff {(index * 5 + offset) % 400}"}}}
            for offset in range(max(1, credits_per_candidate // 2))
        ]
        candidates.append({
            "id": candidate_id,
            "type": "ANIME" if index % 5 else "MANGA",
            "title": {"english": f"Benchmark title {candidate_id}", "romaji": f"Title {candidate_id}"},
            "genres": [GENRES[index % len(GENRES)], GENRES[(index + 2) % len(GENRES)]],
            "tags": [TAGS[index % len(TAGS)], TAGS[(index + 3) % len(TAGS)]],
            "averageScore": 55 + index % 45,
            "popularity": 100 + (index * 137) % 100_000,
            "_recommendation_count": 1 + index % 4,
            "_recommendation_rating": index % 100,
            "characters": {"edges": character_edges},
            "staff": {"edges": staff_edges},
        })
    return candidates


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[position]


def run_benchmark(args: argparse.Namespace) -> dict:
    credit_profile = build_sources(args.sources, args.credits_per_source)
    favorite_works = [
        {"id": index + 1, "type": "ANIME", "rating": 8 + index % 3,
         "genres": [GENRES[index % len(GENRES)]], "tags": [TAGS[index % len(TAGS)]]}
        for index in range(20)
    ]
    favorite_entities = [
        {"entity_type": "character", "entity_id": 10_000 + index * 17}
        for index in range(0, 100, 3)
    ]
    history = {
        index + 1: {
            "feedback": "like" if index % 4 == 0 else "less_like_this" if index % 7 == 0 else None,
            "impressions": index % 12,
            "metadata": {
                "genres": [GENRES[index % len(GENRES)]],
                "tags": [TAGS[(index + 1) % len(TAGS)]],
                "_recommendation_source_ids": [index % max(1, args.sources) + 1],
            },
        }
        for index in range(200)
    }
    results = []
    for count in args.candidate_sizes:
        candidates = build_candidates(count)
        # Warm imports, caches and interpreter paths, but don't include warmups.
        for _ in range(args.warmups):
            rank_candidates(
                candidates, history, favorite_works, rotation=0,
                credit_profile=credit_profile, favorite_entities=favorite_entities,
                voice_language="ALL",
            )
        samples_ms = []
        ranked_count = 0
        for iteration in range(args.iterations):
            started = time.perf_counter()
            ranked = rank_candidates(
                candidates, history, favorite_works, rotation=iteration,
                credit_profile=credit_profile, favorite_entities=favorite_entities,
                voice_language="ALL",
            )
            samples_ms.append((time.perf_counter() - started) * 1000)
            ranked_count = len(ranked)
        results.append({
            "input_candidates": count,
            "ranked_candidates_last_run": ranked_count,
            "source_profiles": args.sources,
            "credits_per_source_profile": args.credits_per_source,
            "iterations": args.iterations,
            "median_ms": round(statistics.median(samples_ms), 3),
            "p95_ms": round(percentile(samples_ms, 0.95), 3),
            "min_ms": round(min(samples_ms), 3),
            "max_ms": round(max(samples_ms), 3),
        })
    return {
        "benchmark": "recommendation_engine.rank_candidates",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "workload": "deterministic synthetic data; CPU-only; no network or database",
        "warmups": args.warmups,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sizes", nargs="+", type=int, default=[50, 250, 500])
    parser.add_argument("--sources", type=int, default=50)
    parser.add_argument("--credits-per-source", type=int, default=24)
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--json-out", type=Path, help="Optional path to write the measurements as JSON.")
    args = parser.parse_args()
    if any(size < 1 or size > 100_000 for size in args.candidate_sizes):
        parser.error("candidate sizes must be between 1 and 100000")
    if not 1 <= args.sources <= 5_000:
        parser.error("--sources must be between 1 and 5000")
    if not 1 <= args.credits_per_source <= 200:
        parser.error("--credits-per-source must be between 1 and 200")
    if not 1 <= args.iterations <= 100:
        parser.error("--iterations must be between 1 and 100")
    if not 0 <= args.warmups <= 20:
        parser.error("--warmups must be between 0 and 20")

    payload = run_benchmark(args)
    print(json.dumps(payload, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
