#!/usr/bin/env python3
"""Load four real, public metadata records into an isolated offline demo database."""
from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    # Never seed the user's normal research database or custom data directory.
    os.environ["ARXIV_RADAR_DATA_DIR"] = str(ROOT / "data/demo")
    os.environ["ARXIV_RADAR_PROFILE"] = str(ROOT / "config/profile.json")
    from radar.service import Radar
    radar = Radar(ROOT)
    source = json.loads((ROOT / "examples/demo-papers.json").read_text(encoding="utf-8"))
    snapshot = source["snapshot_at"]
    run_id = "20260921T060009000000-demo"
    for paper in source["papers"]:
        radar.store.upsert(paper, run_id, snapshot)
    radar.store.save_run({
        "id": run_id, "started_at": snapshot, "finished_at": snapshot,
        "status": "partial", "initial_backfill": True,
        "candidate_count": len(source["papers"]), "relevant_count": len(source["papers"]),
        "new_count": len(source["papers"]), "updated_count": 0,
        "errors": ["OFFLINE DEMO: four selected public records from a fixed snapshot; not a live or complete scan."],
        "coverage": {"since": "2026-09-07T06:00:09Z", "until": snapshot,
                     "complete_window": False, "sources": ["arxiv-api-public-snapshot"],
                     "notes": [source["source"]]},
        "stages": [{"stage": "demo", "message": "Loaded offline metadata snapshot; no network request."}]
    })
    radar.digest()
    print("Loaded the isolated demo in data/demo. No network request was made.")
    print("Start it with: ARXIV_RADAR_DATA_DIR=data/demo python3 -m radar serve")
    print("Live scans use your normal data/ directory unless you explicitly set ARXIV_RADAR_DATA_DIR.")


if __name__ == "__main__":
    main()
