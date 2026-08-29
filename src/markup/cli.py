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

from .config import AppConfig, ConfigError
from .costing import available as costing_methods
from .pipeline import run as run_pipeline
from .report import write_workbook
from .rules.rounding import available as rounding_strategies


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
