"""NekoTrack regression, live API-filter, and bundling diagnostics.

Run from the repository:
    python debug_tools.py
    python debug_tools.py --offline
    python debug_tools.py --bundle-query "Attack on Titan"

Writes nekotrack_diagnostics.json by default. Does not modify the library or
overwrite bundle_tv_debug.json.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
APP_DATA = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "NekoTrack"
sys.path.insert(0, str(ROOT))


def result(name, status, message, **details):
    return {"name": name, "status": status.upper(), "message": str(message), **details}


def media_rows(payload):
    if not isinstance(payload, dict):
        return []
    rows = payload.get("media")
    return rows if isinstance(rows, list) else []


def title_of(item):
    title = item.get("title") or {}
    if isinstance(title, dict):
        return str(title.get("english") or title.get("romaji") or title.get("native") or "")
    return str(title)


def verify_rows(name, payload, validator):
    rows = media_rows(payload)
    if not rows:
        return result(name, "SKIP", "No rows returned; this probe could not verify the filter.")
    problems = []
    for index, item in enumerate(rows):
        issue = validator(item)
        if issue:
            problems.append(f"row {index + 1} ({title_of(item) or item.get('id')}): {issue}")
    if problems:
        return result(name, "FAIL", "; ".join(problems[:5]), checked=len(rows))
    return result(name, "PASS", f"All {len(rows)} returned rows matched.", checked=len(rows))


def run_live_checks(query):
    checks = []
    started = time.monotonic()
    try:
        import api
        import catalog_search
        import series as series_module
        from ui.bundle_options import BUNDLE_OPTION_KEYS
        from ui.preferences import get
    except Exception:
        return [result("Load diagnostic modules", "FAIL", traceback.format_exc())]

    probes = [
        (
            "AniList format filter (ANIME / TV)",
            lambda: api.search_anime(
                query, per_page=8, media_type="ANIME", format_filter="TV",
                sort="POPULARITY_DESC", include_relations=False,
            ),
            lambda item: None if str(item.get("type", "")).upper() == "ANIME"
            and str(item.get("format", "")).upper() == "TV"
            else f"expected ANIME/TV, got {item.get('type')}/{item.get('format')}",
        ),
        (
            "AniList status filter (FINISHED)",
            lambda: api.search_anime(
                "", per_page=5, media_type="ANIME", status="FINISHED",
                sort="POPULARITY_DESC", include_relations=False,
            ),
            lambda item: None if str(item.get("status", "")).upper() == "FINISHED"
            else f"expected FINISHED, got {item.get('status')}",
        ),
        (
            "AniList season/year filter (WINTER 2020)",
            lambda: api.search_anime(
                "", per_page=5, media_type="ANIME", season="WINTER", year="2020",
                sort="POPULARITY_DESC", include_relations=False,
            ),
            lambda item: None if str(item.get("season", "")).upper() == "WINTER"
            and int(item.get("seasonYear") or 0) == 2020
            else f"expected WINTER 2020, got {item.get('season')} {item.get('seasonYear')}",
        ),
        (
            "AniList minimum-score filter (80+)",
            lambda: api.search_anime(
                "", per_page=5, media_type="ANIME", min_score=80,
                sort="SCORE_DESC", include_relations=False,
            ),
            lambda item: None if item.get("averageScore") is not None
            and float(item["averageScore"]) >= 80
            else f"expected score >= 80, got {item.get('averageScore')}",
        ),
        (
            "AniList genre filter (Action)",
            lambda: api.search_anime(
                "", per_page=5, media_type="ANIME", genre="Action",
                sort="POPULARITY_DESC", include_relations=False,
            ),
            lambda item: None if "action" in {
                str(value).casefold() for value in (item.get("genres") or [])
            } else f"Action missing from {item.get('genres')}",
        ),
        (
            "AniList tag filter (Isekai)",
            lambda: api.search_anime(
                "", per_page=5, media_type="ANIME", tag="Isekai",
                sort="POPULARITY_DESC", include_relations=False,
            ),
            lambda item: None if any(
                str(value.get("name", "") if isinstance(value, dict) else value).casefold() == "isekai"
                for value in (item.get("tags") or [])
            ) else "Isekai tag missing from result",
        ),
    ]
    for name, request, validator in probes:
        try:
            checks.append(verify_rows(name, request(), validator))
        except Exception as error:
            checks.append(result(name, "FAIL", str(error)))

    try:
        payload = api.search_mangabaka_media(
            query, page=1, media_type="MANGA", media_format="NOVEL",
            filters={"min_score": 70, "status": "FINISHED", "sort": "SCORE_DESC"},
            limit=8,
        )

        def valid_novel(item):
            raw = item.get("_mangabaka") or {}
            if str(item.get("format") or "").upper() != "NOVEL":
                return f"expected NOVEL, got {item.get('format')}"
            if float(item.get("averageScore") or 0) < 70:
                return f"expected score >= 70, got {item.get('averageScore')}"
            if str(raw.get("status") or "").lower() not in {"completed", "finished"}:
                return f"expected completed status, got {raw.get('status')}"
            if str(raw.get("content_rating") or "").lower() not in {"safe", "suggestive"}:
                return f"unexpected content rating {raw.get('content_rating')}"
            return None

        checks.append(verify_rows("MangaBaka novel/status/score/rating filters", payload, valid_novel))
    except Exception as error:
        checks.append(result("MangaBaka novel/status/score/rating filters", "FAIL", str(error)))

    try:
        payload = api.search_anime(
            "", per_page=6, media_type="ANIME", sort="SCORE_DESC", include_relations=False
        )
        scores = [
            float(item["averageScore"])
            for item in media_rows(payload)
            if item.get("averageScore") is not None
        ]
        if not scores:
            checks.append(result("AniList score sorting", "SKIP", "No scored results returned."))
        elif scores == sorted(scores, reverse=True):
            checks.append(result("AniList score sorting", "PASS", f"Scores are descending: {scores}"))
        else:
            checks.append(result("AniList score sorting", "FAIL", f"Scores are not descending: {scores}"))
    except Exception as error:
        checks.append(result("AniList score sorting", "FAIL", str(error)))

    try:
        combined = catalog_search.search_combined_media(
            query, 1, None, None, {"sort": "SEARCH_MATCH"}, include_relations=False
        )
        rows = media_rows(combined)
        ids = [item.get("id") for item in rows]
        if len(ids) != len(set(ids)):
            checks.append(result("Unified AniList + MangaBaka search", "FAIL", "Duplicate local IDs returned."))
        elif combined.get("_warnings"):
            checks.append(result(
                "Unified AniList + MangaBaka search", "WARN",
                "; ".join(combined["_warnings"]), rows=len(rows),
            ))
        else:
            checks.append(result(
                "Unified AniList + MangaBaka search", "PASS",
                f"Combined search returned {len(rows)} unique rows.",
            ))
    except Exception as error:
        checks.append(result("Unified AniList + MangaBaka search", "FAIL", str(error)))

    try:
        seed_payload = api.search_anime(
            query, per_page=15, media_type="ANIME", sort="POPULARITY_DESC",
            include_relations=True,
        )
        seeds = media_rows(seed_payload)
        if not seeds:
            checks.append(result("Automatic bundling", "SKIP", "AniList returned no seed works.", query=query))
        else:
            app_db = APP_DATA / "anime_tracker.db"
            project_db = ROOT / "anime_tracker.db"
            db_path = app_db if app_db.is_file() else (project_db if project_db.is_file() else None)
            db_note = str(db_path) if db_path else (
                "No existing DB found; saved manual links/exclusions are treated as empty."
            )
            original_cwd = Path.cwd()
            try:
                if db_path:
                    os.chdir(db_path.parent)
                elif original_cwd != ROOT:
                    os.chdir(ROOT)
                with ExitStack() as stack:
                    if db_path is None:
                        stack.enter_context(patch.object(
                            series_module, "get_manual_bundle_links", return_value=[]
                        ))
                        stack.enter_context(patch.object(
                            series_module, "get_bundle_exclusions", return_value=[]
                        ))
                    groups = series_module.group_media_results(
                        seeds, enrich=True, max_requests=4, delay=0
                    )
            finally:
                os.chdir(original_cwd)

            group_rows = []
            for group in groups:
                members = group.get("_series_members") or [group]
                group_rows.append({
                    "representative_id": group.get("id"),
                    "title": title_of(group),
                    "format": group.get("format"),
                    "series_count": len(members),
                    "bundle_summary": group.get("_bundle_summary") or "",
                    "members": [
                        {
                            "id": member.get("id"),
                            "title": title_of(member),
                            "format": member.get("format"),
                            "year": (member.get("startDate") or {}).get("year"),
                        }
                        for member in members
                    ],
                })
            options = {key: bool(get(key)) for key in BUNDLE_OPTION_KEYS}
            checks.append(result(
                "Automatic bundling", "PASS" if groups else "WARN",
                f"Built {len(groups)} groups from {len(seeds)} search results. No library changes made.",
                query=query, seed_count=len(seeds), groups=group_rows,
                bundle_options=options, database=db_note, relation_request_limit=4,
            ))
    except Exception as error:
        checks.append(result("Automatic bundling", "FAIL", str(error), traceback=traceback.format_exc()))

    checks.append(result("Live diagnostics runtime", "PASS", f"{time.monotonic() - started:.1f} seconds"))
    return checks


def main():
    parser = argparse.ArgumentParser(description="Run NekoTrack tests and live API/bundling diagnostics.")
    parser.add_argument("--offline", action="store_true", help="Run local tests only; skip live API checks.")
    parser.add_argument("--bundle-query", default="Re:Zero", help="Series title for the bundle report.")
    parser.add_argument("--report", default="nekotrack_diagnostics.json", help="Output JSON report path.")
    args = parser.parse_args()

    report = {
        "app": "NekoTrack",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(ROOT),
        "read_only_except_report": True,
        "results": [],
    }
    print("NekoTrack diagnostics")
    print("=====================")
    print("Running automated regression tests...")
    try:
        run = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=ROOT, text=True, capture_output=True, timeout=240,
        )
        output = (run.stdout + "\n" + run.stderr).strip()
        state = "PASS" if run.returncode == 0 else "FAIL"
        report["results"].append(result(
            "Automated regression tests", state,
            "All discovered tests passed." if run.returncode == 0 else "One or more tests failed.",
            exit_code=run.returncode, output=output[-16000:],
        ))
        print(output)
        print("Regression tests:", state)
    except Exception as error:
        report["results"].append(result("Automated regression tests", "FAIL", str(error)))
        print("Regression test runner failed:", error)

    if not args.offline:
        print("\nRunning live API and bundling checks...")
        live = run_live_checks(args.bundle_query)
        report["results"].extend(live)
        for item in live:
            print(f"[{item['status']}] {item['name']}: {item['message']}")
            if item["name"] == "Automatic bundling":
                for group in item.get("groups", []):
                    members = ", ".join(
                        f"{member.get('title')} [{member.get('format')} #{member.get('id')}]"
                        for member in group["members"]
                    )
                    print(f"    {group['title']} ({group['series_count']} members): {members}")

    counts = {
        status: sum(1 for item in report["results"] if item["status"] == status)
        for status in ("PASS", "FAIL", "WARN", "SKIP")
    }
    report["summary"] = counts
    output_path = Path(args.report)
    if not output_path.is_absolute():
        output_path = ROOT / output_path
    try:
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as error:
        report["results"].append(result("Write JSON report", "FAIL", str(error)))
        counts["FAIL"] += 1
        print("Could not write report:", error)
    print(
        f"\nSummary: {counts['PASS']} passed, {counts['FAIL']} failed, "
        f"{counts['WARN']} warnings, {counts['SKIP']} skipped."
    )
    print(f"Report: {output_path}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
