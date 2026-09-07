"""HTML writer for ``markup report`` — a self-contained page, no Excel needed.

Same views as the old workbook (summary, biggest movers, category rollup, and the
comparison against the previous run), rendered as one static ``.html`` file that
opens in any browser. Inline CSS, no external assets, safe to email or drop on a
share.
"""

from __future__ import annotations

import datetime as dt
import html
import logging
from pathlib import Path

import pandas as pd

from ..analysis import dashboard_metrics
from ..config import AppConfig
from .excel import MONEY_COLS, PCT_COLS, REPORT_TITLES

log = logging.getLogger(__name__)

# Two-column Metric/Value frames (summary, comparison_summary) carry divider
# rows the analysis layer inserts for readability.
_BLANK_ROW = ("", "")


def _fmt(value: object, column: str) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if column in MONEY_COLS:
            return f"{value:,.2f}"
        if column in PCT_COLS:
            return f"{value:.2f}"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return f"{value:,.2f}" if isinstance(value, float) else str(value)
    return html.escape(str(value))


def _signed_class(column: str, raw: object) -> str:
    """Red/green tint for the movement columns."""
    if column not in {"change_pct", "price_delta", "price_delta_pct", "cost_delta",
                      "price_change", "avg_change_pct"}:
        return ""
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return ""
    if num > 0:
        return " up"
    if num < 0:
        return " down"
    return ""


def _kv_table(df: pd.DataFrame) -> str:
    """Render a Metric/Value frame, promoting '— heading —' rows to sub-heads."""
    out = ['<table class="kv">']
    for metric, value in df.itertuples(index=False):
        metric = "" if metric is None else str(metric)
        if (metric, value) == _BLANK_ROW or (metric == "" and value == ""):
            continue
        if metric.startswith("—") and metric.endswith("—"):
            out.append(f'<tr class="subhead"><th colspan="2">{html.escape(metric.strip("— "))}</th></tr>')
            continue
        out.append(
            f"<tr><th>{html.escape(metric)}</th>"
            f"<td>{_fmt(value, str(metric))}</td></tr>"
        )
    out.append("</table>")
    return "\n".join(out)


def _grid_table(df: pd.DataFrame) -> str:
    if df.empty:
        return '<p class="empty">No rows.</p>'
    cols = list(df.columns)
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    body = []
    for row in df.itertuples(index=False):
        cells = []
        flagged = False
        for col, raw in zip(cols, row):
            if col == "flag_codes" and isinstance(raw, str) and raw.strip():
                flagged = True
            cells.append(f'<td class="c{_signed_class(col, raw)}">{_fmt(raw, col)}</td>')
        cls = ' class="flagged"' if flagged else ""
        body.append(f"<tr{cls}>{''.join(cells)}</tr>")
    return (
        '<div class="scroll"><table class="grid">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 2rem 1.5rem 4rem; background: #f4f5f7; color: #1c1e21;
       font: 15px/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.wrap { max-width: 1180px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
.sub { color: #5c6470; margin: 0 0 2rem; font-size: .9rem; }
section { background: #fff; border: 1px solid #e3e5e8; border-radius: 8px;
          padding: 1.25rem 1.5rem; margin: 0 0 1.25rem; }
h2 { font-size: 1.05rem; margin: 0 0 .9rem; }
table { border-collapse: collapse; width: 100%; font-size: .88rem; }
.scroll { overflow-x: auto; }
.grid th, .grid td { padding: .4rem .6rem; text-align: right; white-space: nowrap;
                     border-bottom: 1px solid #eef0f2; }
.grid th { background: #1f3864; color: #fff; position: sticky; top: 0; font-weight: 600; }
.grid td.c:first-child, .grid th:first-child,
.grid td:nth-child(2) { text-align: left; }
.grid tbody tr:hover { background: #f7f9fc; }
.grid tr.flagged td { background: #fff4e5; }
.grid td.up { color: #157347; }
.grid td.down { color: #c02b2b; }
.kv { width: auto; min-width: 340px; }
.kv th { text-align: left; padding: .3rem 1.5rem .3rem 0; font-weight: 500; color: #3a3f47; }
.kv td { text-align: right; padding: .3rem 0; font-variant-numeric: tabular-nums; }
.kv tr.subhead th { padding-top: 1rem; color: #1f3864; font-weight: 700;
                    text-transform: uppercase; font-size: .74rem; letter-spacing: .04em; }
.empty { color: #8a929c; font-style: italic; }
footer { color: #8a929c; font-size: .8rem; margin-top: 2rem; text-align: center; }

/* -- dashboard -- */
.dash h2 { display: flex; align-items: baseline; gap: .6rem; }
.dash h2 .tag { font-size: .68rem; font-weight: 700; letter-spacing: .05em;
                text-transform: uppercase; color: #8a929c; }
.verdict { border-left: 4px solid #157347; background: #f0f7f2; border-radius: 4px;
           padding: .8rem 1rem; margin: 0 0 1.2rem; font-size: .95rem; }
.verdict.warn { border-left-color: #b8860b; background: #fbf6ea; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr));
         gap: .8rem; margin: 0 0 1.2rem; }
.tile { border: 1px solid #e3e5e8; border-radius: 8px; padding: .9rem 1rem; background: #fbfcfd; }
.tile .n { font-size: 1.7rem; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
.tile .l { font-size: .8rem; color: #5c6470; margin-top: .2rem; }
.tile .h { font-size: .72rem; color: #9099a3; margin-top: .35rem; }
.tile.alert .n { color: #b8860b; }
.panel { margin: 1.1rem 0 0; }
.panel h3 { font-size: .8rem; text-transform: uppercase; letter-spacing: .04em;
            color: #1f3864; margin: 0 0 .5rem; }
.mini { width: 100%; font-size: .84rem; }
.mini td { padding: .3rem .5rem .3rem 0; border-bottom: 1px solid #eef0f2; vertical-align: top; }
.mini td.r { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.chart { margin: .4rem 0 .2rem; }
.chart .row { display: grid; grid-template-columns: 168px 1fr 54px; align-items: center;
              gap: .5rem; padding: .12rem 0; font-size: .82rem; }
.chart .row .cap { color: #3a3f47; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chart .track { position: relative; background: #eef0f2; border-radius: 3px; height: 15px; }
.chart .fill { position: absolute; left: 0; top: 0; bottom: 0; background: #3a5a9c; border-radius: 3px; }
.chart .fill.warn { background: #d99a1c; }
.chart .val { text-align: right; font-variant-numeric: tabular-nums; color: #3a3f47; }
.note { font-size: .82rem; color: #5c6470; margin: .5rem 0 0; }
.detail-lead { font-size: 1.15rem; margin: 2.4rem 0 .8rem; padding-top: 1.2rem;
               border-top: 2px solid #d7dbe0; color: #5c6470; }
"""


def _tile(n: object, label: str, hint: str = "", alert: bool = False) -> str:
    cls = " alert" if alert else ""
    hint_html = f'<div class="h">{html.escape(hint)}</div>' if hint else ""
    return (
        f'<div class="tile{cls}"><div class="n">{html.escape(str(n))}</div>'
        f'<div class="l">{html.escape(label)}</div>{hint_html}</div>'
    )


def _bar_rows(items, vmax: float, danger_below: float | None, fmt: str) -> str:
    rows = []
    for label, value in items:
        pct = max(0.0, min(100.0, (float(value) / vmax * 100) if vmax else 0))
        warn = danger_below is not None and float(value) < danger_below
        rows.append(
            f'<div class="row"><span class="cap" title="{html.escape(str(label))}">'
            f"{html.escape(str(label))}</span>"
            f'<span class="track"><span class="fill{" warn" if warn else ""}" '
            f'style="width:{pct:.1f}%"></span></span>'
            f'<span class="val">{fmt.format(value)}</span></div>'
        )
    return "".join(rows)


def _bar_chart(items, *, vmax=None, danger_below=None, fmt="{:.1f}%") -> str:
    if not items:
        return '<p class="empty">No data.</p>'
    vmax = vmax or (max(float(v) for _, v in items) * 1.08) or 1
    return f'<div class="chart">{_bar_rows(items, vmax, danger_below, fmt)}</div>'


def _dashboard(detail, stats: dict, group_col: str) -> str:
    m = dashboard_metrics(detail, stats, group_col)
    cur = m["currency"]

    held_block = "".join(
        f'<tr><td><strong>{html.escape(h["sku"])}</strong><br>'
        f'<span style="color:#5c6470">{html.escape(str(h["product_name"])[:60])}</span><br>'
        f'<span style="color:#8a929c;font-size:.9em">{html.escape(h["reason"])}</span></td>'
        f'<td class="r">{cur} {h["current_price"]:,.2f}</td></tr>'
        if h["current_price"] is not None else
        f'<tr><td><strong>{html.escape(h["sku"])}</strong><br>'
        f'<span style="color:#8a929c">{html.escape(h["reason"])}</span></td><td class="r">—</td></tr>'
        for h in m["held"]
    ) or '<tr><td colspan="2" class="empty">Nothing held — every priced SKU is on the upload.</td></tr>'

    src_rows = [(lbl, n) for lbl, n in m["cost_sources"]]

    cat_items = [(f'{c["name"]}  ({c["skus"]})', c["avg_margin"]) for c in m["categories"]]

    verdict_warn = m["blocked"] > 0
    verdict = (
        f'{"Safe to publish, with items to note." if verdict_warn else "Safe to publish."} '
        f'{m["priced"]} of {m["in_scope"]} SKUs priced. '
        f'{m["blocked"]} held for a decision — nothing safe to send. '
        f'{m["advisory"]} ship with an advisory flag (a price cut, a large move, or a '
        f'standard-cost routing note); none block the upload.'
    )

    thin = [c for c in m["categories"] if c["avg_margin"] < 10]
    n_below = sum(c["n_below_10"] for c in m["categories"])
    thin_txt = (
        "Thinnest categories: "
        + ", ".join(f'{c["name"]} {c["avg_margin"]}%' for c in thin[:4])
        + f' — {n_below} SKUs across the whole book sit under 10% margin, mostly '
        "low-value drinks where rounding to the nearest whole baht bites hardest."
    ) if thin else f"No category averages below 10% ({n_below} individual SKUs do)."

    big = [c for c in m["categories"] if c["skus"] >= 3]
    movers = sorted(big, key=lambda c: abs(c["avg_change"]), reverse=True)[:3]
    move_txt = "Biggest shifts this round: " + ", ".join(
        f'{c["name"]} {"+" if c["avg_change"] >= 0 else ""}{c["avg_change"]}% '
        f'({c["skus"]} SKUs)' for c in movers
    ) + " — standard-cost catch-up on items with no recent purchase, not market moves."

    return f"""
<section class="dash">
<h2>This pricing round <span class="tag">at a glance</span></h2>
<div class="verdict{' warn' if verdict_warn else ''}">{html.escape(verdict)}</div>
<div class="tiles">
{_tile(f'{m["priced"]} / {m["in_scope"]}', "Catalogue priced")}
{_tile(f'{m["avg_margin"]}%', "Average margin", "unweighted mean across SKUs")}
{_tile(m["moving_up"] + m["moving_down"], "Prices moving",
       f'{m["moving_up"]} up · {m["moving_down"]} down · {m["flat"]} flat')}
{_tile(m["blocked"], "Held for your decision", alert=m["blocked"] > 0)}
{_tile(m["advisory"], "Ship with an advisory flag")}
{_tile(f'{m["cost_conf_pct"]}%', "Costed from actual purchases",
       f'{m["breach_up"] + m["breach_down"]} moves beyond the ±25% guardrail')}
</div>
<div class="panel"><h3>Held for a decision</h3>
<table class="mini"><tbody>{held_block}</tbody></table></div>
<div class="panel"><h3>Where each price came from</h3>
{_bar_chart(src_rows, fmt="{:.0f}", vmax=(max((n for _, n in src_rows), default=1) * 1.08))}
<p class="note">A cost from an actual goods receipt is the most reliable. A standard
cost means no purchase landed in the {html.escape(str(m["window"]))} window —
{m["cost_conf_pct"]}% of prices rest on a real recent purchase.</p></div>
</section>

<section class="dash">
<h2>Margin &amp; movement <span class="tag">by category</span></h2>
<div class="chart">
{_bar_rows(cat_items, max(c[1] for c in cat_items) * 1.08, 10.0, "{:.1f}%")}
</div>
<p class="note">Catalogue average <strong>{m["avg_margin"]}%</strong>. Bars in amber
average below 10%. Averages are unweighted — there is no sales volume in the data.</p>
<p class="note">{html.escape(thin_txt)}</p>
<p class="note">{html.escape(move_txt)}</p>
<div class="panel" style="margin-top:1.4rem"><h3>How the whole book is spread</h3>
<div class="chart">
{_bar_rows(m["margin_buckets"], (max(n for _, n in m["margin_buckets"]) * 1.08) or 1, None, "{:.0f}")}
</div>
<p class="note">Each band is a count of SKUs. Nothing prices at a loss; nothing sits above 30%.</p></div>
</section>
"""


def write_report_html(
    views: dict, cfg: AppConfig, path: Path, *, run_id: str | None = None,
    detail=None, stats: dict | None = None,
) -> Path:
    """Write the analysis views produced by ``markup report`` as one HTML page.

    When ``detail`` and ``stats`` are supplied, two director-facing dashboard
    sections are rendered ahead of the analyst tables.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    summary = views.get("summary")
    run_window = ""
    if summary is not None and not summary.empty:
        run_window = dict(zip(summary["Metric"], summary["Value"])).get("Costing window", "")

    run_id = run_id or path.stem.removeprefix("report_")

    blocks = []
    if detail is not None and not detail.empty:
        try:
            blocks.append(_dashboard(detail, stats or {}, "category"))
        except Exception:  # a dashboard glitch must never lose the report
            log.exception("Dashboard section failed — writing the tables only")

    detail_heading = bool(blocks)
    order = ["summary", "comparison_summary", "comparison", "movers", "category"]
    for key in order:
        df = views.get(key)
        if df is None:
            continue
        title = REPORT_TITLES.get(key, key.replace("_", " ").title())
        table = _kv_table(df) if key in {"summary", "comparison_summary"} else _grid_table(df)
        lead = ""
        if detail_heading:
            lead = '<h2 class="detail-lead">Full detail</h2>'
            detail_heading = False
        blocks.append(f"{lead}<section><h2>{html.escape(title)}</h2>{table}</section>")

    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pricing report — {html.escape(run_id)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<h1>Pricing report</h1>
<p class="sub">Run <strong>{html.escape(run_id)}</strong>
{('· ' + html.escape(str(run_window))) if run_window else ''}
· {html.escape(cfg.currency)} · generated {generated}</p>
{''.join(blocks)}
<footer>Markup Pricing Engine · this is a read-only view of a recorded run</footer>
</div>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")
    log.info("Report written: %s", path)
    return path
