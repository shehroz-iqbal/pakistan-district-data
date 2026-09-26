"""Step 1: download every pinned source file into data/raw and verify checksums.

    python -m pipeline.fetch          # download + verify against sources.lock.json
    python -m pipeline.fetch --lock   # (maintainers) re-pin: rewrite the lock file

Raw files are never edited. Corrections happen downstream (config/fixes.yml), so
anyone can diff our outputs against the untouched inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from .common import CONFIG, RAW, load_yaml

LOCK_PATH = CONFIG / "sources.lock.json"


def planned_files() -> list[dict]:
    """Expand config/sources.yml into a flat list of {source, path, url, local}."""
    cfg = load_yaml("sources.yml")
    files = []

    census = cfg["census_2023"]
    templates = {**census["district_tables"], **census["tehsil_tables"]}
    for key, template in templates.items():
        for province in census["provinces"]:
            path = template.format(province=province)
            files.append(
                {
                    "source": "census_2023",
                    "table": key,
                    "province": province,
                    "path": path,
                    "url": census["url_template"].format(
                        commit=census["pinned_commit"], path=urllib.parse.quote(path)
                    ),
                    "local": f"census_2023/{key}_{province}.csv",
                }
            )

    gb = cfg["geoboundaries_pak"]
    for key, meta in gb["files"].items():
        files.append(
            {
                "source": "geoboundaries_pak",
                "table": key,
                "province": None,
                "path": meta["path"],
                "url": gb["url_template"].format(commit=gb["pinned_commit"], path=meta["path"]),
                "local": f"geoboundaries/{key}.geojson",
            }
        )
    return files


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "pakistan-district-data"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return response.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", action="store_true", help="rewrite sources.lock.json")
    args = parser.parse_args(argv)

    lock = {} if args.lock or not LOCK_PATH.exists() else json.loads(LOCK_PATH.read_text())
    if not lock and not args.lock:
        print("No sources.lock.json found; run with --lock first.", file=sys.stderr)
        return 1

    new_lock, problems = {}, []
    for item in planned_files():
        target = RAW / item["local"]
        data = _download(item["url"])
        digest = hashlib.sha256(data).hexdigest()
        if not args.lock:
            expected = lock.get(item["local"], {}).get("sha256")
            if digest != expected:
                problems.append(f"{item['local']}: sha256 {digest[:12]}… expected {str(expected)[:12]}…")
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        new_lock[item["local"]] = {"url": item["url"], "sha256": digest, "bytes": len(data)}
        print(f"ok  {item['local']}  ({len(data):,} bytes)")

    if problems:
        print("\nUpstream files changed since they were pinned:", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        print("Review the change, then re-pin with --lock.", file=sys.stderr)
        return 1

    if args.lock:
        payload = {
            "_generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **dict(sorted(new_lock.items())),
        }
        LOCK_PATH.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"\nWrote {LOCK_PATH.relative_to(CONFIG.parent)} ({len(new_lock)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
