"""Server-rendered HTML for the dashboard. Every figure is formatted here by Python, as in Telegram.

No page carries a secret, and the only script is Telegram's login widget on the sign-in page.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal

from lens.backtest.report import to_markdown
from lens.dashboard.queries import (
    BriefingDetail,
    BriefingSummary,
    Health,
    PortfolioPoint,
    ReportDetail,
    ReportSummary,
    SignalEvent,
    SignalSummary,
)
from lens.delivery.format import long_day, money, price, r_multiple, short_day

NAV = (
    ("/", "Overview"),
    ("/briefings", "Briefings"),
    ("/portfolio", "Portfolio"),
    ("/signals", "Signals"),
    ("/backtests", "Backtests"),
    ("/health", "Health"),
)

CSS = """
:root{--carbon:#07110e;--graphite:#101a16;--paper:#f0eee7;--fog:#8d9992;--mint:#79d5c2;--loss:#e88078;
--rule:rgb(141 153 146/.22);--rule-strong:rgb(141 153 146/.42);color-scheme:dark}
*{box-sizing:border-box}html{background:var(--carbon);color:var(--paper)}
body{margin:0;font:16px/1.55 system-ui,sans-serif}
a{color:var(--paper);text-underline-offset:.22em}:focus-visible{outline:2px solid var(--paper);outline-offset:3px}
header{border-bottom:1px solid var(--rule);display:flex;gap:1.5rem;align-items:center;
  padding:.9rem 1.25rem;flex-wrap:wrap}
header strong{font-weight:600;letter-spacing:.02em}header nav{display:flex;gap:1.1rem;flex-wrap:wrap;flex:1}
header nav a{color:var(--fog);text-decoration:none}header nav a[aria-current=page]{color:var(--paper)}
main{max-width:72rem;margin:0 auto;padding:1.5rem 1.25rem 4rem}
h1{font-size:2rem;font-weight:600;margin:.5rem 0 1rem}h2{font-size:1.15rem;font-weight:600;margin:2rem 0 .6rem}
.mono,td.n,code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-variant-numeric:tabular-nums}
table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{text-align:left;padding:.5rem .9rem .5rem 0;border-bottom:1px solid var(--rule);vertical-align:top}
th{color:var(--fog);font-weight:400;font-size:.8rem}td.n{text-align:right}
.wrap{overflow-x:auto}.muted{color:var(--fog)}.ok{color:var(--mint)}.bad{color:var(--loss)}
.message{background:var(--graphite);border:1px solid var(--rule-strong);padding:1rem 1.2rem;
  white-space:pre-wrap;overflow-wrap:anywhere;margin-bottom:.75rem}
.message em{font-style:normal;color:var(--fog)}
pre{white-space:pre-wrap;background:var(--graphite);border:1px solid var(--rule);padding:1rem}
form.inline{display:flex;gap:.6rem;align-items:end;flex-wrap:wrap}
label{display:grid;gap:.2rem;font-size:.8rem;color:var(--fog)}
input,select,button{font:inherit;background:var(--graphite);color:var(--paper);
  border:1px solid var(--rule-strong);padding:.35rem .6rem}
button{cursor:pointer}svg{display:block;width:100%;height:auto}
.chart-wrap{overflow-x:auto;margin:1rem 0 .4rem}.chart-wrap svg{min-width:640px}
.chart text{fill:var(--fog);font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
.chart text.label{fill:var(--paper)}.chart .grid{stroke:var(--rule);stroke-width:1}
.chart .line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.chart .equity{stroke:var(--paper)}.chart .hit{fill:transparent}
.chart .s-1{stroke:#3987e5}.chart .s-2{stroke:#d95926}.chart .s-3{stroke:#199e70}.chart .s-4{stroke:#c98500}
.chart circle.end{stroke:none}.chart circle.equity{fill:var(--paper)}
.chart circle.s-1,.swatch.s-1{fill:#3987e5;background:#3987e5}
.chart circle.s-2,.swatch.s-2{fill:#d95926;background:#d95926}
.chart circle.s-3,.swatch.s-3{fill:#199e70;background:#199e70}
.chart circle.s-4,.swatch.s-4{fill:#c98500;background:#c98500}
.legend{display:flex;gap:1.1rem;flex-wrap:wrap;list-style:none;padding:0;margin:0 0 1rem;
  font-size:.85rem;color:var(--fog)}
.swatch{display:inline-block;width:.75rem;height:.75rem;border-radius:2px;margin-right:.4rem;
  vertical-align:-.05rem}
"""

# Exposure colours follow the asset class, never its rank (validated for the dark surface).
SERIES_SLOT = {"stock": "s-1", "etf": "s-2", "crypto": "s-3"}

_TAG = re.compile(r"<(/?)(b|i|code)>")
_MARKS = {"b": "strong", "i": "em", "code": "code"}


def esc(value: object) -> str:
    return html.escape(str(value))


def telegram_html(chunk: str) -> str:
    """The renderer's Telegram HTML, rebuilt so only bold, italic and code survive."""
    out: list[str] = []
    last = 0
    for match in _TAG.finditer(chunk):
        out.append(html.escape(html.unescape(chunk[last : match.start()]), quote=False))
        out.append(f"<{match.group(1)}{_MARKS[match.group(2)]}>")
        last = match.end()
    out.append(html.escape(html.unescape(chunk[last:]), quote=False))
    return "".join(out)


def when(moment: datetime | None) -> str:
    return f"{moment:%Y-%m-%d %H:%M} UTC" if moment else "n/a"


def tone(status: str) -> str:
    """A run's status is its delivery state: delivered is fine, running is neutral, the rest needs a look."""
    if status in {"SENT", "RESENT"}:
        return "ok"
    return "muted" if status == "RUNNING" else "bad"


def _r(value: Decimal | None) -> str:
    return r_multiple(value) if value is not None else "n/a"


def table(
    head: Sequence[str], rows: Iterable[Sequence[str]], numeric: frozenset[int] = frozenset()
) -> str:
    """Cells are HTML already; callers escape text."""
    th = "".join(f"<th scope='col'>{esc(h)}</th>" for h in head)
    body = "".join(
        "<tr>"
        + "".join(
            f"<td class='n'>{c}</td>" if i in numeric else f"<td>{c}</td>"
            for i, c in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    if not body:
        body = f"<tr><td colspan='{len(head)}' class='muted'>Nothing recorded yet.</td></tr>"
    return (
        f"<div class='wrap'><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def layout(title: str, body: str, *, current: str = "", signed_in: bool = True) -> str:
    nav = ""
    if signed_in:
        links = "".join(
            f"<a href='{href}'{' aria-current=page' if href == current else ''}>{esc(label)}</a>"
            for href, label in NAV
        )
        nav = (
            f"<nav aria-label='Dashboard'>{links}</nav>"
            "<form method='post' action='/logout'><button type='submit'>Sign out</button></form>"
        )
    return (
        "<!doctype html><html lang='en-MY'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex,nofollow'>"
        f"<title>{esc(title)} · Goldirham Lens</title><link rel='stylesheet' href='/dashboard.css'></head>"
        f"<body><header><strong>Goldirham Lens</strong>{nav}</header><main>{body}</main></body></html>"
    )


def login(bot_username: str, auth_url: str) -> str:
    widget = (
        "<script async src='https://telegram.org/js/telegram-widget.js?22' "
        f"data-telegram-login='{esc(bot_username)}' data-size='large' "
        f"data-auth-url='{esc(auth_url)}'></script>"
    )
    body = (
        "<h1>Sign in</h1><p class='muted'>Only the owner's Telegram account is accepted. "
        "Telegram signs the sign-in, and the server checks it before setting a 12-hour session.</p>"
        f"{widget}"
    )
    return layout("Sign in", body, signed_in=False)


def message(title: str, text: str) -> str:
    return layout(title, f"<h1>{esc(title)}</h1><p>{esc(text)}</p>", signed_in=False)


def overview(latest: BriefingSummary | None, health: Health) -> str:
    run = health.runs[0] if health.runs else None
    latest_html = (
        f"<p><a href='/briefings/{latest.day.isoformat()}'>{esc(long_day(latest.day))}</a> · "
        f"{esc(latest.mode)} · delivery {esc(latest.delivery or 'none')}</p>"
        if latest
        else "<p class='muted'>No briefing stored yet.</p>"
    )
    run_html = (
        f"<p>{esc(run.briefing_date.isoformat())} · {esc(run.trigger)} · "
        f"<span class='{tone(run.status)}'>{esc(run.status)}</span> · "
        f"started {esc(when(run.started_at))}</p>"
        if run
        else "<p class='muted'>No run recorded yet.</p>"
    )
    body = f"<h1>Overview</h1><h2>Latest briefing</h2>{latest_html}<h2>Latest run</h2>{run_html}"
    return layout("Overview", body, current="/")


def briefing_list(items: list[BriefingSummary]) -> str:
    rows = [
        (
            f"<a href='/briefings/{b.day.isoformat()}'>{esc(long_day(b.day))}</a>",
            esc(b.mode),
            esc(b.delivery or "none"),
            esc(when(b.sent_at)),
            esc(b.messages),
        )
        for b in items
    ]
    body = "<h1>Briefings</h1>" + table(
        ("Date", "Mode", "Delivery", "Sent", "Messages"), rows, frozenset({4})
    )
    return layout("Briefings", body, current="/briefings")


def briefing_page(detail: BriefingDetail) -> str:
    messages = "".join(
        f"<article class='message'>{telegram_html(c)}</article>" for c in detail.chunks
    )
    meta = f"{esc(detail.mode)} · delivery {esc(detail.delivery or 'none')}"
    if detail.resolution:
        meta += f" · {esc(detail.resolution)}"
    body = f"<h1>{esc(long_day(detail.day))}</h1><p class='muted'>{meta}</p>{messages}"
    return layout(long_day(detail.day), body, current="/briefings")


Series = tuple[str, str, list[tuple[date, Decimal]]]
_W, _H, _LEFT, _RIGHT, _TOP, _BOTTOM = 720, 240, 104, 112, 12, 30
_LINE = 14


def _day(day: date) -> str:
    return f"{short_day(day)} {day.year}"


def line_chart(
    series: Sequence[Series],
    *,
    label: str,
    value: Callable[[Decimal], str],
    low: Decimal | None = None,
    high: Decimal | None = None,
) -> str:
    """An SVG line chart of (name, css class, [(day, value)]) series.

    Each point's title is its tooltip, and every series' last value is labelled at the line end.
    """
    days = sorted({d for _, _, pts in series for d, _ in pts})
    values = [v for _, _, pts in series for _, v in pts]
    if len(days) < 2 or not values:
        return ""
    bottom = min(values) if low is None else low
    top = max(values) if high is None else high
    span = (top - bottom) or Decimal(1)
    first, reach = days[0], (days[-1] - days[0]).days
    plot_w, plot_h = _W - _LEFT - _RIGHT, _H - _TOP - _BOTTOM

    def x(day: date) -> float:
        return _LEFT + plot_w * (day - first).days / reach

    def y(v: Decimal) -> float:
        return _TOP + plot_h * float((top - v) / span)

    ends: list[tuple[float, float, str]] = []
    parts = [
        f"<line class='grid' x1='{_LEFT}' x2='{_W - _RIGHT}' y1='{y(tick):.1f}' "
        f"y2='{y(tick):.1f}'/><text x='{_LEFT - 8}' y='{y(tick) + 4:.1f}' "
        f"text-anchor='end'>{esc(value(tick))}</text>"
        for tick in (top, bottom + span / 2, bottom)
    ]
    parts.append(f"<text x='{_LEFT}' y='{_H - 8}'>{esc(_day(days[0]))}</text>")
    parts.append(
        f"<text x='{_W - _RIGHT}' y='{_H - 8}' text-anchor='end'>{esc(_day(days[-1]))}</text>"
    )
    for name, css, points in series:
        if not points:
            continue
        path = " ".join(
            f"{'M' if i == 0 else 'L'}{x(d):.1f} {y(v):.1f}" for i, (d, v) in enumerate(points)
        )
        parts.append(f"<path class='line {css}' d='{path}'/>")
        prefix = f", {esc(name)}" if len(series) > 1 else ""
        parts += [
            f"<circle class='hit' cx='{x(d):.1f}' cy='{y(v):.1f}' r='7'>"
            f"<title>{esc(_day(d))}{prefix}: {esc(value(v))}</title></circle>"
            for d, v in points
        ]
        end_day, end_value = points[-1]
        tag = f"{name} {value(end_value)}" if len(series) > 1 else value(end_value)
        parts.append(
            f"<circle class='end {css}' cx='{x(end_day):.1f}' cy='{y(end_value):.1f}' r='4'/>"
        )
        ends.append((y(end_value) + 4, x(end_day) + 9, tag))
    previous = float("-inf")
    for label_y, label_x, tag in sorted(ends):
        label_y = max(label_y, previous + _LINE)
        previous = label_y
        parts.append(f"<text class='label' x='{label_x:.1f}' y='{label_y:.1f}'>{esc(tag)}</text>")
    svg = (
        f"<div class='chart-wrap'><svg class='chart' viewBox='0 0 {_W} {_H}' role='img' "
        f"aria-label='{esc(label)}'>" + "".join(parts) + "</svg></div>"
    )
    if len(series) < 2:
        return svg
    legend = "".join(
        f"<li><span class='swatch {css}'></span>{esc(name)}</li>" for name, css, _ in series
    )
    return f"{svg}<ul class='legend'>{legend}</ul>"


def _exposure_chart(points: list[PortfolioPoint]) -> str:
    classes = [c for c in SERIES_SLOT if any(c in p.exposure for p in points)]
    classes += sorted({c for p in points for c in p.exposure} - set(classes))
    series: list[Series] = [
        (
            name,
            SERIES_SLOT.get(name, "s-4"),
            [(p.day, p.exposure[name]) for p in points if name in p.exposure],
        )
        for name in classes
    ]
    return line_chart(
        series,
        label=(
            "Exposure by asset class, percent of the valued portfolio, "
            f"{_day(points[0].day)} to {_day(points[-1].day)}"
        ),
        value=lambda v: f"{v:.1f}%",
        low=Decimal(0),
        high=Decimal(100),
    )


def portfolio(points: list[PortfolioPoint]) -> str:
    rows = [(esc(p.day.isoformat()), esc(money(p.total, p.currency))) for p in reversed(points)]
    charts = ""
    if len(points) >= 2:
        currency = points[-1].currency
        charts = line_chart(
            [("Total", "equity", [(p.day, p.total) for p in points])],
            label=(
                f"Portfolio value in {currency} by briefing date, "
                f"{_day(points[0].day)} to {_day(points[-1].day)}"
            ),
            value=lambda v: money(v, currency),
        )
        exposure = _exposure_chart(points)
        if exposure:
            charts += f"<h2>Exposure by asset class</h2>{exposure}"
    body = (
        "<h1>Portfolio history</h1><p class='muted'>The total from each stored briefing, in the base "
        f"currency, valued with that day's verified marks and FX.</p>{charts}"
        + table(("Briefing date", "Total"), rows, frozenset({1}))
    )
    return layout("Portfolio", body, current="/portfolio")


STATUSES = ("", "OPEN", "STOPPED", "T2_HIT", "EXPIRED", "UNVERIFIABLE")


def signal_list(items: list[SignalSummary], status: str, symbol: str) -> str:
    options = "".join(
        f"<option value='{s}'{' selected' if s == status else ''}>{s or 'Any'}</option>"
        for s in STATUSES
    )
    form = (
        "<form class='inline' method='get' action='/signals'>"
        f"<label>Status<select name='status'>{options}</select></label>"
        f"<label>Symbol<input name='symbol' value='{esc(symbol)}' maxlength='24'></label>"
        "<button type='submit'>Filter</button></form>"
    )
    rows = [
        (
            f"<a href='/signals/{s.id}'>{esc(s.symbol)}</a>",
            esc(s.signal_day.isoformat()),
            esc(s.status),
            esc(price(s.entry, s.currency)),
            esc(price(s.stop, s.currency)),
            esc(price(s.t2, s.currency)),
            esc(_r(s.outcome_r)),
            f"<span class='mono'>{esc(s.strategy)} {esc(s.version)}</span>",
        )
        for s in items
    ]
    body = f"<h1>Signals</h1>{form}" + table(
        ("Asset", "Signal day", "Status", "Entry", "Stop", "T2", "Outcome", "Strategy"),
        rows,
        frozenset({3, 4, 5, 6}),
    )
    return layout("Signals", body, current="/signals")


def signal_page(item: SignalSummary, events: list[SignalEvent]) -> str:
    levels = table(
        ("Entry", "Stop", "T1", "T2"),
        [tuple(esc(price(v, item.currency)) for v in (item.entry, item.stop, item.t1, item.t2))],
        frozenset({0, 1, 2, 3}),
    )
    rows = [
        (
            esc(e.kind),
            esc(short_day(e.day)),
            esc(price(e.price, item.currency)) if e.price is not None else "n/a",
            esc(_r(e.r)),
        )
        for e in events
    ]
    body = (
        f"<h1>{esc(item.symbol)} · {esc(item.signal_day.isoformat())}</h1>"
        f"<p class='muted'>{esc(item.strategy)} {esc(item.version)} · {esc(item.status)}</p>{levels}"
        "<h2>Events</h2>" + table(("Event", "Day", "Price", "R"), rows, frozenset({2, 3}))
    )
    return layout(item.symbol, body, current="/signals")


def report_list(items: list[ReportSummary]) -> str:
    rows = [
        (
            f"<a href='/backtests/{r.id}'>{esc(r.name)}</a>",
            f"<span class='mono'>{esc(r.version)}</span>",
            esc(f"{r.from_day.isoformat()} to {r.to_day.isoformat()}"),
            "<span class='ok'>live</span>" if r.active else "<span class='muted'>research</span>",
            f"<span class='mono'>{esc(r.report_hash[:16])}</span>",
        )
        for r in items
    ]
    body = "<h1>Backtest reports</h1>" + table(
        ("Strategy", "Version", "Period", "Status", "Report hash"), rows
    )
    return layout("Backtests", body, current="/backtests")


def report_page(detail: ReportDetail) -> str:
    s = detail.summary
    body = (
        f"<h1>{esc(s.name)} <span class='mono muted'>{esc(s.version)}</span></h1>"
        f"<pre>{esc(to_markdown(detail.body, s.report_hash[:16]))}</pre>"
    )
    return layout(s.name, body, current="/backtests")


def health_page(h: Health) -> str:
    runs = [
        (
            esc(r.briefing_date.isoformat()),
            esc(r.trigger),
            f"<span class='{tone(r.status)}'>{esc(r.status)}</span>",
            esc(r.error_class or ""),
            esc(when(r.started_at)),
            esc(f"{(r.finished_at - r.started_at).total_seconds():.1f}s")
            if r.finished_at
            else "running",
        )
        for r in h.runs
    ]
    stages = [
        (esc(s.stage), esc(s.outcome), esc(f"{s.seconds:.2f}s"), esc(s.error_class or ""))
        for s in h.stages
    ]
    deliveries = [(esc(day.isoformat()), esc(state)) for day, state in h.deliveries]
    events = [
        (esc(e.kind), esc(e.severity), esc(e.source), esc(when(e.occurred_at))) for e in h.events
    ]
    body = (
        "<h1>Health</h1>"
        f"<p>AI spend in the last 7 days: <span class='mono'>{esc(money(h.ai_spend_7d, 'USD'))}</span></p>"
        "<h2>Runs</h2>"
        + table(
            ("Briefing date", "Trigger", "Status", "Error", "Started", "Duration"),
            runs,
            frozenset({5}),
        )
        + "<h2>Stages of the latest run</h2>"
        + table(("Stage", "Outcome", "Time", "Error"), stages, frozenset({2}))
        + "<h2>Deliveries</h2>"
        + table(("Briefing date", "State"), deliveries)
        + "<h2>Operational events</h2>"
        + table(("Kind", "Severity", "Source", "When"), events)
    )
    return layout("Health", body, current="/health")
