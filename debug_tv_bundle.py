import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import api
import series


class Log:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("w", encoding="utf-8")

    def write(self, text=""):
        text = str(text)
        print(text)
        self.handle.write(text + "\n")
        self.handle.flush()

    def close(self):
        self.handle.close()


def title(item):
    value = item.get("title") or {}
    if isinstance(value, dict):
        return value.get("english") or value.get("romaji") or value.get("native") or "<untitled>"
    return str(value)


def describe(item):
    start = item.get("startDate") or {}
    return (
        f"id={item.get('id')} title={title(item)!r} type={item.get('type')} "
        f"format={item.get('format')} episodes={item.get('episodes')} year={start.get('year')}"
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose NekoTrack bundling for the exact catalog-browse path "
            "used by an empty search box + Anime type + TV format filter."
        )
    )
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--per-page", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--output", default="bundle_tv_debug.log")
    args = parser.parse_args()

    log = Log(args.output)
    old_cache = dict(series._relation_cache)

    try:
        series._relation_cache.clear()

        log.write("=" * 100)
        log.write("NEKOTRACK TV-FILTER BUNDLE DIAGNOSTIC")
        log.write(f"timestamp={time.strftime('%Y-%m-%d %H:%M:%S')}")
        log.write("search='' (EMPTY SEARCH BOX)")
        log.write(
            f"filters: media_type=ANIME format_filter=TV sort=SEARCH_MATCH "
            f"pages={args.pages} per_page={args.per_page}"
        )
        log.write(f"SERIES_RELATIONS={sorted(series.SERIES_RELATIONS)}")
        log.write("")

        results = []
        for page in range(1, max(1, args.pages) + 1):
            log.write(f"SEARCH page={page} EMPTY_QUERY")
            payload = api.search_anime(
                "",
                page=page,
                per_page=args.per_page,
                media_type="ANIME",
                format_filter="TV",
                sort="SEARCH_MATCH",
            )
            info = payload.get("pageInfo") or {}
            page_results = payload.get("media") or []
            log.write(
                f"SEARCH_RESULT page={page} count={len(page_results)} "
                f"current={info.get('currentPage')} last={info.get('lastPage')} has_next={info.get('hasNextPage')}"
            )
            for item in page_results:
                results.append(item)
                log.write(f"  SEED {describe(item)}")
                for edge in (item.get("relations") or {}).get("edges", []):
                    node = edge.get("node") or {}
                    log.write(
                        f"    SEARCH_REL {item.get('id')} --{edge.get('relationType')}--> "
                        f"{node.get('id')} {title(node)!r} type={node.get('type')} format={node.get('format')}"
                    )
            if not info.get("hasNextPage"):
                break

        log.write("")
        log.write(f"SEED_TOTAL {len(results)} ids={[int(x['id']) for x in results]}")
        log.write("")
        log.write("RUNNING SERIES GROUPING WITH FULL ENRICHMENT")

        original_cache = series._cache_relation_details_batch
        original_allowed = series._relation_edge_allowed
        original_apply = series._apply_relation_details
        original_discover = series._discover_related
        original_group = series._group_discovered
        original_logical = series._bundle_logical_season_count

        def cache_wrapper(media_ids):
            requested = [int(x) for x in media_ids]
            log.write(f"RELATION_REQUEST ids={requested}")
            result = original_cache(media_ids)
            returned = sorted(int(x) for x in result)
            missing = sorted(set(requested) - set(returned))
            log.write(f"RELATION_RESPONSE returned={returned} missing={missing}")
            for media_id in returned:
                details = result[media_id]
                edges = (details.get("relations") or {}).get("edges", [])
                log.write(f"  NODE {describe(details)} relation_count={len(edges)}")
                for edge in edges:
                    node = edge.get("node") or {}
                    log.write(
                        f"    REL {media_id} --{edge.get('relationType')}--> "
                        f"{node.get('id')} {title(node)!r} type={node.get('type')} format={node.get('format')}"
                    )
            return result

        def apply_wrapper(item, details):
            original_apply(item, details)
            log.write(f"HYDRATED {describe(item)}")

        def allowed_wrapper(item, edge):
            node = edge.get("node") or {}
            result = original_allowed(item, edge)
            left_family = series._media_family(item)
            right_family = series._media_family(node)
            log.write(
                f"EDGE_DECISION allowed={result} relation={edge.get('relationType')} "
                f"source={item.get('id')} {title(item)!r} family={left_family} format={item.get('format')} "
                f"target={node.get('id')} {title(node)!r} family={right_family} format={node.get('format')}"
            )
            return result

        def discover_wrapper(items, **kwargs):
            log.write("=" * 100)
            log.write("DISCOVERY START")
            log.write(f"seed_count={len(items)} seed_ids={[int(item['id']) for item in items]}")
            result, requests_used = original_discover(items, **kwargs)
            log.write(f"DISCOVERY END discovered={len(result)} requests_used={requests_used}")
            for item in result:
                log.write(f"  DISCOVERED {describe(item)} related_only={item.get('_related_only', False)} loaded={item.get('_relations_loaded', False)}")
            return result, requests_used

        def group_wrapper(results_arg, discovered):
            log.write("=" * 100)
            log.write(f"GROUPING START original={len(results_arg)} discovered={len(discovered)}")
            grouped = original_group(results_arg, discovered)
            log.write(f"GROUPING END groups={len(grouped)}")
            for index, item in enumerate(grouped, 1):
                members = item.get("_series_members") or []
                log.write(
                    f"  GROUP {index}: representative={int(item['id'])} {title(item)!r} "
                    f"count={item.get('_series_count')} summary={item.get('_bundle_summary')!r}"
                )
                for member in members:
                    log.write(f"    MEMBER {describe(member)}")
            return grouped

        def logical_wrapper(members):
            value = original_logical(members)
            tv = [m for m in members if str(m.get("format") or "").upper() in {"TV", "TV_SHORT"}]
            log.write(
                f"SEASON_COUNT result={value} tv={[(int(m['id']), title(m)) for m in tv]}"
            )
            return value

        series._cache_relation_details_batch = cache_wrapper
        series._apply_relation_details = apply_wrapper
        series._relation_edge_allowed = allowed_wrapper
        series._discover_related = discover_wrapper
        series._group_discovered = group_wrapper
        series._bundle_logical_season_count = logical_wrapper

        grouped = series.group_media_results(
            results,
            enrich=True,
            max_requests=0,
            delay=args.delay,
        )

        log.write("")
        log.write("FINAL_GROUPS")
        for index, item in enumerate(grouped, 1):
            members = item.get("_series_members") or []
            log.write(
                f"GROUP {index}: representative={item.get('id')} title={title(item)!r} "
                f"series_count={item.get('_series_count')} summary={item.get('_bundle_summary')!r}"
            )
            for member in members:
                log.write(f"  MEMBER {describe(member)}")

        result = {
            "search": "",
            "filter": "TV",
            "media_type": "ANIME",
            "sort": "SEARCH_MATCH",
            "seed_count": len(results),
            "seed_ids": [int(x["id"]) for x in results],
            "groups": [
                {
                    "representative": int(x["id"]),
                    "title": title(x),
                    "series_count": x.get("_series_count"),
                    "summary": x.get("_bundle_summary"),
                    "members": [
                        {
                            "id": int(m["id"]),
                            "title": title(m),
                            "type": m.get("type"),
                            "format": m.get("format"),
                            "episodes": m.get("episodes"),
                        }
                        for m in (x.get("_series_members") or [])
                    ],
                }
                for x in grouped
            ],
        }
        json_path = Path(args.output).with_suffix(".json")
        json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        log.write(f"JSON={json_path}")
        log.write("DONE")

    except Exception as exc:
        log.write(f"FATAL {type(exc).__name__}: {exc}")
        raise
    finally:
        series._relation_cache.clear()
        series._relation_cache.update(old_cache)
        try:
            series._cache_relation_details_batch = original_cache
            series._apply_relation_details = original_apply
            series._relation_edge_allowed = original_allowed
            series._discover_related = original_discover
            series._group_discovered = original_group
            series._bundle_logical_season_count = original_logical
        except NameError:
            pass
        log.close()


if __name__ == "__main__":
    main()
