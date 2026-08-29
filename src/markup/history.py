"""Run history — what makes 'compare against the previous run' possible.

Every ``markup update`` snapshots its Detail frame and a manifest of the
parameters that produced it into ``data/output/history/``. Nothing else in the
pipeline depends on this, so history can be cleared at any time without
affecting pricing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import AppConfig

log = logging.getLogger(__name__)
HISTORY_DIRNAME = "history"


@dataclass
class RunRecord:
    run_id: str
    manifest: dict
    detail_path: Path

    @property
    def when(self) -> str:
        return self.manifest.get("stats", {}).get("Run timestamp", self.run_id)

    @property
    def label(self) -> str:
        s = self.manifest.get("stats", {})
        return f"{self.run_id}  ({s.get('Costing method')}, {s.get('Period (days)')}d)"

    def detail(self) -> pd.DataFrame:
        return pd.read_csv(self.detail_path)


def history_dir(cfg: AppConfig) -> Path:
    d = cfg.resolve(cfg.out_dir) / HISTORY_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _next_run_id(d: Path) -> str:
    """A run id unique within ``d``.

    Always ``YYYYmmdd_HHMMSS_NNN``. The sequence suffix is never omitted, so
    ids from the same second still sort chronologically as plain strings —
    which is what ``list_runs`` relies on.
    """
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for seq in range(1, 1000):
        candidate = f"{stamp}_{seq:03d}"
        if not (d / f"{candidate}_manifest.json").exists():
            return candidate
    raise RuntimeError(f"could not allocate a unique run id for {stamp}")


def save_run(cfg: AppConfig, result, workbook: Path | None) -> RunRecord:
    """Snapshot a completed run. Returns the record just written."""
    d = history_dir(cfg)
    run_id = _next_run_id(d)

    detail_path = d / f"{run_id}_detail.csv"
    result.detail.to_csv(detail_path, index=False)

    manifest = {
        "run_id": run_id,
        "workbook": str(workbook) if workbook else None,
        "stats": {k: (str(v) if isinstance(v, Path) else v) for k, v in result.stats.items()},
    }
    (d / f"{run_id}_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )
    log.info("Run %s snapshotted to history", run_id)
    return RunRecord(run_id, manifest, detail_path)


def list_runs(cfg: AppConfig, limit: int | None = None) -> list[RunRecord]:
    """All snapshotted runs, newest first."""
    d = history_dir(cfg)
    records: list[RunRecord] = []
    for man in sorted(d.glob("*_manifest.json"), reverse=True):
        run_id = man.name.replace("_manifest.json", "")
        detail = d / f"{run_id}_detail.csv"
        if not detail.exists():
            continue
        try:
            manifest = json.loads(man.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("Skipping unreadable manifest %s", man.name)
            continue
        records.append(RunRecord(run_id, manifest, detail))
        if limit and len(records) >= limit:
            break
    return records


def prune(cfg: AppConfig, keep: int = 24) -> int:
    """Keep the newest ``keep`` runs; delete the rest. Returns how many went."""
    runs = list_runs(cfg)
    removed = 0
    for record in runs[keep:]:
        record.detail_path.unlink(missing_ok=True)
        (record.detail_path.parent / f"{record.run_id}_manifest.json").unlink(missing_ok=True)
        removed += 1
    return removed
