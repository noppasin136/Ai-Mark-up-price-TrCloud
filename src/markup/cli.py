"""Command-line entry point.

    python -m markup run --period 60 --method fifo

Every flag mirrors a key in ``config.yaml`` and overrides it for that run only,
so the committed config stays the team's agreed baseline while you experiment.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from . import analysis, history
from .config import AppConfig, ConfigError
from .costing import available as costing_methods
from .io.loaders import _read_any
from .io.schemas import REQUIRED, SchemaError, resolve_columns
from .pipeline import run as run_pipeline
from .report import write_report_workbook, write_workbook
from .rules.rounding import available as rounding_strategies

DEFAULT_INPUTS = {
    "gr2": "data/input/GR2.xlsx",
    "w10": "data/input/W10.xlsx",
    "markup_list": "data/input/markup_list.xlsx",
    "sale_list": "data/input/sale_list.xlsx",
}
INPUT_EXTS = (".xlsx", ".xls", ".xlsm", ".csv")


def _find_input(cfg: AppConfig, dataset: str) -> Path | None:
    """Locate an input by its default name, tolerating any supported extension."""
    stem = Path(DEFAULT_INPUTS[dataset]).stem
    folder = cfg.resolve("data/input")
    for ext in INPUT_EXTS:
        candidate = folder / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    # last resort: a case-insensitive stem match
    for candidate in folder.glob("*"):
        if candidate.suffix.lower() in INPUT_EXTS and candidate.stem.lower() == stem.lower():
            return candidate
    return None


def _setup_logging(level: str, log_file: str | None, root: Path) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        p = root / log_file
        p.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(p, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s  %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


@click.group()
@click.version_option(package_name="markup-pricing")
def cli() -> None:
    """Markup pricing engine."""


@cli.command("run")
@click.option("--config", "config_path", default="config/config.yaml", show_default=True)
@click.option("--mapping", "mapping_path", default="config/column_mapping.yaml", show_default=True)
@click.option("--gr2", default="data/input/GR2.xlsx", show_default=True, help="Goods receipt report")
@click.option("--w10", default="data/input/W10.xlsx", show_default=True, help="Current price report")
@click.option("--markup", "markup_path", default="data/input/markup_list.xlsx", show_default=True)
@click.option("--sale-list", default=None, help="Optional SKU scope list")
@click.option("--period", type=int, default=None, help="Override run.period_days (30/60/90/...)")
@click.option("--method", type=click.Choice(sorted(costing_methods())), default=None,
              help="Override costing.method")
@click.option("--as-of", default=None, help="Override run.as_of_date (YYYY-MM-DD)")
@click.option("--rounding", type=click.Choice(sorted(rounding_strategies())), default=None,
              help="Override rounding.strategy")
@click.option("--step", type=float, default=None, help="Override rounding.step")
@click.option("--default-markup", type=float, default=None, help="Override markup.default_pct")
@click.option("--out", default=None, help="Explicit output .xlsx path")
@click.option("--dry-run", is_flag=True, help="Compute and summarise without writing the workbook")
def run_cmd(config_path, mapping_path, gr2, w10, markup_path, sale_list, period, method,
            as_of, rounding, step, default_markup, out, dry_run):
    """Cost the GR2 receipts, apply markup, and write the Excel workbook."""
    overrides = {
        "run.period_days": period,
        "run.as_of_date": as_of,
        "costing.method": method,
        "rounding.strategy": rounding,
        "rounding.step": step,
        "markup.default_pct": default_markup,
    }
    if rounding or step:
        # An explicit rounding override on the command line means "this rule,
        # everywhere" — otherwise a configured band would silently win.
        overrides["rounding.use_bands"] = False
    try:
        cfg = AppConfig.load(config_path, mapping_path, overrides)
    except ConfigError as exc:
        raise click.ClickException(f"Configuration problem: {exc}") from None

    _setup_logging(cfg.log_level, cfg.log_file, cfg.root)

    try:
        result = run_pipeline(cfg, gr2, w10, markup_path, sale_list)
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None

    click.echo("")
    for k, v in result.stats.items():
        click.echo(f"  {k:<28} {v}")
    click.echo("")

    if dry_run:
        click.secho("Dry run — no workbook written.", fg="yellow")
        return

    path = write_workbook(result, cfg, out)
    click.secho(f"Workbook written: {path}", fg="green")
    if result.stats.get("SKUs blocked from upload"):
        click.secho(
            f"  {result.stats['SKUs blocked from upload']} SKU(s) held back — see the "
            "Exceptions sheet before uploading.",
            fg="yellow",
        )


@cli.command("validate")
@click.option("--config", "config_path", default="config/config.yaml", show_default=True)
@click.option("--mapping", "mapping_path", default="config/column_mapping.yaml", show_default=True)
def validate_cmd(config_path, mapping_path):
    """Check config.yaml for contradictions without running anything."""
    try:
        cfg = AppConfig.load(config_path, mapping_path)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from None
    click.secho("Configuration is valid.", fg="green")
    click.echo(f"  Window   {cfg.window_start} .. {cfg.window_end}  ({cfg.period_days} days)")
    click.echo(f"  Costing  {cfg.method} (fallback: {cfg.fallback_method})")
    click.echo(f"  Rounding {cfg.rounding.strategy} step {cfg.rounding.step}, "
               f"{len(cfg.rounding_bands)} band(s)")


@cli.command("methods")
def methods_cmd():
    """List the costing methods and rounding strategies available."""
    click.echo("Costing methods:   " + ", ".join(costing_methods()))
    click.echo("Rounding strategies: " + ", ".join(rounding_strategies()))


if __name__ == "__main__":
    cli()


@cli.command("check")
@click.option("--config", "config_path", default="config/config.yaml", show_default=True)
@click.option("--mapping", "mapping_path", default="config/column_mapping.yaml", show_default=True)
def check_cmd(config_path, mapping_path):
    """Inspect data/input/ — what is present, and whether the columns map."""
    cfg = AppConfig.load(config_path, mapping_path)
    logging.disable(logging.CRITICAL)

    click.echo(f"\nInput folder: {cfg.resolve('data/input')}\n")
    problems = 0

    for dataset in ("gr2", "w10", "markup_list", "sale_list"):
        optional = dataset == "sale_list"
        path = _find_input(cfg, dataset)
        label = f"{dataset:<12}"

        if path is None:
            if optional:
                click.echo(f"  {label} - not present (optional; all W10 SKUs will be priced)")
            else:
                click.secho(f"  {label} MISSING  expected {DEFAULT_INPUTS[dataset]}", fg="red")
                problems += 1
            continue

        try:
            spec = cfg.mapping.get(dataset) or {}
            raw = _read_any(path, spec.get("sheet", 0), int(spec.get("header_row", 0)))
            raw = raw.dropna(how="all")
            resolved = resolve_columns(raw, dataset, cfg.mapping)
            found = [c for c in REQUIRED.get(dataset, ()) if c in resolved.columns]
            click.secho(
                f"  {label} OK  {len(raw):>6} rows  {path.name}  "
                f"(required columns found: {', '.join(found)})",
                fg="green",
            )
            optional_missing = [
                c for c in (cfg.mapping.get(dataset, {}).get("columns") or {})
                if c not in resolved.columns
            ]
            if optional_missing:
                click.echo(f"               unmapped optional columns: {', '.join(optional_missing)}")
        except SchemaError as exc:
            click.secho(f"  {label} COLUMN PROBLEM", fg="red")
            for line in str(exc).splitlines():
                click.echo(f"               {line}")
            problems += 1
        except Exception as exc:  # noqa: BLE001
            click.secho(f"  {label} UNREADABLE  {exc}", fg="red")
            problems += 1

    click.echo("")
    if problems:
        click.secho(
            f"{problems} problem(s). Fix the header spellings in {mapping_path}, "
            "then run 'markup check' again.",
            fg="red",
        )
        raise SystemExit(1)
    click.secho("All inputs look good. Run 'markup update' to price them.", fg="green")


@cli.command("update")
@click.option("--config", "config_path", default="config/config.yaml", show_default=True)
@click.option("--mapping", "mapping_path", default="config/column_mapping.yaml", show_default=True)
@click.option("--period", type=int, default=None, help="Override run.period_days")
@click.option("--method", type=click.Choice(sorted(costing_methods())), default=None,
              help="Override costing.method")
@click.option("--as-of", default=None, help="Override run.as_of_date (YYYY-MM-DD)")
@click.option("--keep-history", type=int, default=24, show_default=True,
              help="How many past runs to retain")
def update_cmd(config_path, mapping_path, period, method, as_of, keep_history):
    """Re-price everything from data/input/ and snapshot the run.

    This is the everyday command: it finds the ERP files by their standard
    names, prices them, writes the workbook, and records the run so that
    'markup report' can compare against it next time.
    """
    overrides = {
        "run.period_days": period,
        "run.as_of_date": as_of,
        "costing.method": method,
    }
    try:
        cfg = AppConfig.load(config_path, mapping_path, overrides)
    except ConfigError as exc:
        raise click.ClickException(f"Configuration problem: {exc}") from None

    _setup_logging(cfg.log_level, cfg.log_file, cfg.root)

    paths = {name: _find_input(cfg, name) for name in DEFAULT_INPUTS}
    missing = [n for n in ("gr2", "w10", "markup_list") if paths[n] is None]
    if missing:
        raise click.ClickException(
            "Missing required input(s): "
            + ", ".join(f"{DEFAULT_INPUTS[n]}" for n in missing)
            + "\n  Put the ERP exports in data/input/ using those names, "
            "then run 'markup check'."
        )

    try:
        result = run_pipeline(
            cfg, paths["gr2"], paths["w10"], paths["markup_list"], paths["sale_list"]
        )
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None

    workbook = write_workbook(result, cfg)
    record = history.save_run(cfg, result, workbook)
    pruned = history.prune(cfg, keep=keep_history)

    click.echo("")
    for k, v in result.stats.items():
        click.echo(f"  {k:<28} {v}")
    click.echo("")
    click.secho(f"Workbook:  {workbook}", fg="green")
    click.echo(f"Run id:    {record.run_id}")
    if pruned:
        click.echo(f"Pruned {pruned} old history snapshot(s)")
    blocked = result.stats.get("SKUs blocked from upload", 0)
    if blocked:
        click.secho(
            f"{blocked} SKU(s) held back — check the Exceptions sheet before uploading.",
            fg="yellow",
        )
    click.echo("Run 'markup report' for the summary and a comparison with the previous run.")


@cli.command("report")
@click.option("--config", "config_path", default="config/config.yaml", show_default=True)
@click.option("--mapping", "mapping_path", default="config/column_mapping.yaml", show_default=True)
@click.option("--against", default=None,
              help="Run id to compare against (default: the run before the latest)")
@click.option("--top", type=int, default=25, show_default=True, help="How many movers to list")
@click.option("--out", default=None, help="Explicit output .xlsx path")
@click.option("--group-by", default="category", show_default=True,
              help="Column for the rollup: category | subcategory | department | brand")
def report_cmd(config_path, mapping_path, against, top, out, group_by):
    """Summarise the latest run, compare it with the previous one, roll up by group."""
    cfg = AppConfig.load(config_path, mapping_path)
    _setup_logging(cfg.log_level, cfg.log_file, cfg.root)

    runs = history.list_runs(cfg)
    if not runs:
        raise click.ClickException(
            "No run history yet. Run 'markup update' first — it records each run "
            "so reports can compare them."
        )

    current = runs[0]
    detail = current.detail()
    stats = current.manifest.get("stats", {})

    if against:
        previous = next((r for r in runs if r.run_id == against), None)
        if previous is None:
            raise click.ClickException(
                f"No run '{against}'. Available: {', '.join(r.run_id for r in runs[:10])}"
            )
    else:
        previous = runs[1] if len(runs) > 1 else None

    views = {
        "summary": analysis.summary_view(detail, stats),
        "movers": analysis.movers_view(detail, top),
        "category": analysis.category_rollup(detail, group_by),
    }
    if previous is not None:
        comparison = analysis.comparison_view(detail, previous.detail())
        views["comparison_summary"] = analysis.comparison_summary(
            comparison, current.label, previous.label
        )
        views["comparison"] = comparison

    path = Path(out) if out else cfg.resolve(cfg.out_dir) / f"report_{current.run_id}.xlsx"
    write_report_workbook(views, cfg, path)

    # -- console digest, so the numbers are readable without opening Excel ----
    click.echo("")
    click.secho(f"Report for run {current.run_id}", bold=True)
    for key in ("Costing method", "Period (days)", "Costing window", "SKUs priced",
                "SKUs blocked from upload", "Average margin %", "Upload rows"):
        if key in stats:
            click.echo(f"  {key:<28} {stats[key]}")

    roll = views["category"]
    if not roll.empty and group_by in roll.columns:
        click.echo(f"\n  By {group_by}:")
        click.echo(f"    {'group':<16}{'skus':>6}{'avg margin %':>14}{'avg change %':>14}")
        for _, r in roll.iterrows():
            click.echo(
                f"    {str(r[group_by])[:15]:<16}{int(r['skus']):>6}"
                f"{r['avg_margin_pct']:>14}{r['avg_change_pct']:>14}"
            )

    if previous is not None:
        cs = dict(zip(views["comparison_summary"]["Metric"], views["comparison_summary"]["Value"]))
        click.echo(f"\n  vs run {previous.run_id}:")
        for key in ("Changed", "Unchanged", "New (not priced before)",
                    "Dropped (no longer priced)", "Average change %"):
            if key in cs:
                click.echo(f"    {key:<28} {cs[key]}")
    else:
        click.echo("\n  (no earlier run to compare against yet)")

    click.echo("")
    click.secho(f"Report written: {path}", fg="green")


@cli.command("runs")
@click.option("--config", "config_path", default="config/config.yaml", show_default=True)
@click.option("--mapping", "mapping_path", default="config/column_mapping.yaml", show_default=True)
@click.option("--limit", type=int, default=15, show_default=True)
def runs_cmd(config_path, mapping_path, limit):
    """List recorded runs, newest first."""
    cfg = AppConfig.load(config_path, mapping_path)
    logging.disable(logging.CRITICAL)
    runs = history.list_runs(cfg, limit)
    if not runs:
        click.echo("No runs recorded yet. Run 'markup update'.")
        return
    click.echo(f"\n  {'run id':<22}{'method':<20}{'period':>8}{'priced':>9}{'blocked':>9}")
    for r in runs:
        s = r.manifest.get("stats", {})
        click.echo(
            f"  {r.run_id:<22}{str(s.get('Costing method')):<20}"
            f"{str(s.get('Period (days)')):>8}{str(s.get('SKUs priced')):>9}"
            f"{str(s.get('SKUs blocked from upload')):>9}"
        )
    click.echo("")
