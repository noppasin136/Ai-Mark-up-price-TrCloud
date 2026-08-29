from pathlib import Path

import pandas as pd

from markup import history
from markup.config import AppConfig
from markup.pipeline import RunResult

ROOT = Path(__file__).resolve().parent.parent


def _cfg(tmp_path):
    cfg = AppConfig.load(ROOT / "config/config.yaml", ROOT / "config/column_mapping.yaml")
    cfg.out_dir = tmp_path
    return cfg


def _result(n=3):
    detail = pd.DataFrame({"sku": [f"S{i}" for i in range(n)], "suggested_price": [10.0] * n})
    empty = pd.DataFrame()
    return RunResult(detail, empty, empty, empty, empty, {"Costing method": "fifo",
                                                          "Period (days)": 90})


def test_save_then_list_round_trips(tmp_path):
    cfg = _cfg(tmp_path)
    record = history.save_run(cfg, _result(), workbook=None)
    runs = history.list_runs(cfg)
    assert len(runs) == 1
    assert runs[0].run_id == record.run_id
    assert len(runs[0].detail()) == 3


def test_list_returns_newest_first(tmp_path):
    cfg = _cfg(tmp_path)
    for _ in range(3):
        history.save_run(cfg, _result(), workbook=None)
    ids = [r.run_id for r in history.list_runs(cfg)]
    assert ids == sorted(ids, reverse=True)


def test_prune_keeps_only_the_newest(tmp_path):
    cfg = _cfg(tmp_path)
    for _ in range(5):
        history.save_run(cfg, _result(), workbook=None)
    removed = history.prune(cfg, keep=2)
    assert removed == 3
    assert len(history.list_runs(cfg)) == 2


def test_missing_history_is_not_an_error(tmp_path):
    assert history.list_runs(_cfg(tmp_path / "nothing-here")) == []
