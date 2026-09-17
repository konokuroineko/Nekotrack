import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import api
import series


class DebugLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("w", encoding="utf-8")

    def write(self, message=""):
        line = str(message)
        print(line)
        self.handle.write(line + "\n")
        self.handle.flush()

    def close(self):
        self.handle.close()


def title(item):
    value = item.get("title") or {}
    if isinstance(value, dict):
        return value.get("english") or value.get("romaji") or value.get("native") or "<untitled>"
    return str(value)


def fmt(item):
    return str(item.get("format") or "?")


def describe(item):
    return f"{int(item['id'])} | {title(item)} | type={item.get('type')} format={fmt(item)} episodes={item.get('episodes')} year={(item.get('startDate') or {}).get('year')}"


def edge_description(item, edge):
    node = edge.get("node") or {}
    return (
        f"{int(item['id'])} [{title(item)}] --{edge.get('relationType')}--> "
        f"{node.get('id')} [{title(node)}] "
        f"type={node.get('type')} format={node.get('format')}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Trace NekoTrack AniList series discovery and grouping for one search."
    )
    parser.add_argument("search", help="Exact search text that reproduces the bundling problem")
    parser.add_argument(
        "--pages",
        type=int,
        default=3,
        help="Number of AniList search pages to collect (default: 3)",
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=20,
        help="Search results per page (default: 20)",
    )
    parser.add_argument(
        "--max-nodes",
        type=int,
        default=2000,
        help="Maximum relation nodes to discover (default: 2000)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay between relation batches in seconds (default: 0)",
    )
    parser.add_argument(
        "--output",
        default="bundle_debug.log",
        help="Text log path (default: bundle_debug.log)",
    )
    args = parser.parse_args()

    log = DebugLog(args.output)
    phase = {"value": "startup"}
    original_cache = series._cache_relation_details_batch
    original_apply = series._apply_relation_details
    original_allowed = series._relation_edge_allowed
    original_discover = series._discover_related
    original_group = series._group_discovered
    original_logical = series._bundle_logical_season_count

    try:
        # Fresh process normally starts empty, but clear it explicitly so the
        # diagnostic never hides a missing request behind an inherited cache.
        series._relation_cache.clear()

        log.write("=" * 100)
        log.write("NEKOTRACK SERIES BUNDLE DIAGNOSTIC")
        log.write(f"timestamp={time.strftime('%Y-%m-%d %H:%M:%S')}")
        log.write(f"search={args.search!r}")
        log.write(f"pages={args.pages} per_page={args.per_page} max_nodes={args.max_nodes}")
        log.write(f"allowed_relation_types={sorted(series.SERIES_RELATIONS)}")
        log.write(f"anime_bundle_formats={sorted(series.ANIME_BUNDLE_FORMATS)}")
        log.write("")

        def cache_wrapper(media_ids):
            requested = [int(x) for x in media_ids]
            log.write(f"CACHE_FETCH requested={requested}")
            try:
                result = original_cache(media_ids)
                log.write(f"CACHE_FETCH returned={sorted(int(x) for x in result)} missing={sorted(set(requested) - set(int(x) for x in result))}")
                for media_id, details in result.items():
                    if details:
                        edges = (details.get("relations") or {}).get("edges", [])
                        log.write(
                            f"  DETAIL {media_id}: type={details.get('type')} format={details.get('format')} "
                            f"title={title(details)!r} relations={len(edges)}"
                        )
                return result
            except Exception as exc:
                log.write(f"CACHE_FETCH EXCEPTION {type(exc).__name__}: {exc}")
                raise

        def apply_wrapper(item, details):
            original_apply(item, details)
            edges = series._search_relation_edges(item)
            log.write(
                f"HYDRATE {int(item['id'])}: title={title(item)!r} format={fmt(item)} "
                f"relations_loaded={item.get('_relations_loaded')} edges={len(edges)}"
            )

        def allowed_wrapper(item, edge):
            result = original_allowed(item, edge)
            node = edge.get("node") or {}
            source_family = series._media_family(item)
            target_family = series._media_family(node)
            log.write(
                f"EDGE_CHECK phase={phase['value']} allowed={result} "
                f"relation={edge.get('relationType')} source={item.get('id')}({source_family}/{fmt(item)}) "
                f"target={node.get('id')}({target_family}/{node.get('format')})"
            )
            return result

        def discover_wrapper(items, **kwargs):
            phase["value"] = "discovery"
            log.write("=" * 100)
            log.write("DISCOVERY START")
            log.write(f"seed_count={len(items)} seed_ids={[int(item['id']) for item in items]}")
            result, requests_used = original_discover(items, **kwargs)
            log.write(f"DISCOVERY END discovered={len(result)} requests_used={requests_used}")
            for item in result:
                log.write(f"  DISCOVERED {describe(item)} related_only={item.get('_related_only', False)} loaded={item.get('_relations_loaded', False)}")
            return result, requests_used

        def group_wrapper(results, discovered):
            phase["value"] = "grouping"
            log.write("=" * 100)
            log.write(f"GROUPING START original={len(results)} discovered={len(discovered)}")
            grouped = original_group(results, discovered)
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
            log.write(
                f"SEASON_COUNT input={[(int(m['id']), title(m), fmt(m)) for m in members if fmt(m) in {'TV', 'TV_SHORT'}]} result={value}"
            )
            return value

        series._cache_relation_details_batch = cache_wrapper
        series._apply_relation_details = apply_wrapper
        series._relation_edge_allowed = allowed_wrapper
        series._discover_related = discover_wrapper
        series._group_discovered = group_wrapper
        series._bundle_logical_season_count = logical_wrapper

        results = []
        page_info = None
        for page in range(1, max(1, args.pages) + 1):
            log.write(f"SEARCH page={page} query={args.search!r}")
            payload = api.search_anime(
                args.search,
                page=page,
                per_page=args.per_page,
                media_type="ANIME",
                sort="SEARCH_MATCH",
            )
            page_info = payload.get("pageInfo") or {}
            page_results = payload.get("media") or []
            log.write(
                f"SEARCH_RESULT page={page} count={len(page_results)} "
                f"hasNextPage={page_info.get('hasNextPage')} lastPage={page_info.get('lastPage')}"
            )
            for item in page_results:
                results.append(item)
                log.write(f"  SEARCH_ITEM {describe(item)} relations={len(series._search_relation_edges(item))}")
            if not page_info.get("hasNextPage"):
                break

        log.write("")
        log.write(f"COMBINED_SEARCH_RESULTS count={len(results)}")
        log.write(f"COMBINED_IDS={[int(item['id']) for item in results]}")

        grouped = series.group_media_results(
            results,
            enrich=True,
            max_requests=0,
            delay=args.delay,
        )

        log.write("")
        log.write("FINAL DIAGNOSTIC SUMMARY")
        log.write(f"search_results={len(results)}")
        log.write(f"relation_cache_entries={len(series._relation_cache)}")
        log.write(f"grouped_results={len(grouped)}")
        for item in grouped:
            members = item.get("_series_members") or []
            tv = [m for m in members if fmt(m) in {"TV", "TV_SHORT"}]
            log.write(
                f"FINAL_GROUP representative={item.get('id')} title={title(item)!r} "
                f"series_count={item.get('_series_count')} logical_summary={item.get('_bundle_summary')!r} "
                f"tv_members={[(int(m['id']), title(m), fmt(m)) for m in tv]}"
            )

        json_path = Path(args.output).with_suffix(".json")
        json_data = {
            "search": args.search,
            "pages": args.pages,
            "per_page": args.per_page,
            "search_results": [
                {"id": int(x["id"]), "title": title(x), "type": x.get("type"), "format": x.get("format")}
                for x in results
            ],
            "groups": [
                {
                    "representative_id": int(x["id"]),
                    "representative_title": title(x),
                    "series_count": x.get("_series_count"),
                    "summary": x.get("_bundle_summary"),
                    "members": [
                        {"id": int(m["id"]), "title": title(m), "type": m.get("type"), "format": m.get("format"), "episodes": m.get("episodes")}
                        for m in (x.get("_series_members") or [])
                    ],
                }
                for x in grouped
            ],
        }
        json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.write(f"MACHINE_READABLE_LOG={json_path}")
        log.write("DONE")
    except Exception as exc:
        log.write(f"FATAL {type(exc).__name__}: {exc}")
        raise
    finally:
        # Restore patched functions so importing this module from another tool
        # in the same interpreter cannot leave diagnostics active.
        series._cache_relation_details_batch = original_cache
        series._apply_relation_details = original_apply
        series._relation_edge_allowed = original_allowed
        series._discover_related = original_discover
        series._group_discovered = original_group
        series._bundle_logical_season_count = original_logical
        log.close()


if __name__ == "__main__":
    main()
