"""Private dashboard (FastAPI). Every page needs the owner's signed session, and nothing writes.

The app reads through a read-only database role inside `SET TRANSACTION READ ONLY`, sets its own
cookie key, and answers 503 when any of its settings are missing.
"""

# No `from __future__ import annotations` here: FastAPI must see the dependency annotations, which
# refer to names local to create_app, as real objects.
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from lens.dashboard import pages, queries
from lens.dashboard.auth import (
    COOKIE,
    MIN_SECRET_LENGTH,
    SESSION_MAX_AGE,
    issue_session,
    read_session,
    verify_login,
)
from lens.logs import configure_logging, get_logger
from lens.settings import Secrets
from lens.storage.db import Database

log = get_logger("lens.dashboard")

CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self' https://telegram.org https://t.me data:; "
    "script-src https://telegram.org; frame-src https://oauth.telegram.org; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    db: Database
    owner_id: int
    bot_token: str
    bot_username: str
    session_secret: str
    secure_cookies: bool = True
    clock: Callable[[], datetime] = field(default=_now)


def config_from_env() -> DashboardConfig | None:
    secrets = Secrets()
    configure_logging(secrets.secret_values())
    url, secret = secrets.dashboard_database_url, secrets.dashboard_session_secret
    if (
        url is None
        or secret is None
        or secrets.telegram_bot_token is None
        or secrets.owner_telegram_id is None
        or not secrets.telegram_bot_username
    ):
        return None
    if len(secret.get_secret_value()) < MIN_SECRET_LENGTH:
        log.warning("dashboard session secret is too short", minimum=MIN_SECRET_LENGTH)
        return None
    return DashboardConfig(
        Database(url.get_secret_value(), pooled=True, read_only=True),
        secrets.owner_telegram_id,
        secrets.telegram_bot_token.get_secret_value(),
        secrets.telegram_bot_username,
        secret.get_secret_value(),
    )


class NotConfiguredError(Exception):
    pass


class LoginRequiredError(Exception):
    pass


def create_app(provider: Callable[[], DashboardConfig | None] = config_from_env) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    cache: dict[str, DashboardConfig | None] = {}

    def config() -> DashboardConfig:
        if "config" not in cache:
            cache["config"] = provider()
        found = cache["config"]
        if found is None:
            raise NotConfiguredError
        return found

    def owner(
        request: Request, cfg: Annotated[DashboardConfig, Depends(config)]
    ) -> DashboardConfig:
        token = request.cookies.get(COOKIE)
        if not read_session(
            token, secret=cfg.session_secret, owner_id=cfg.owner_id, now=cfg.clock()
        ):
            raise LoginRequiredError
        return cfg

    Owner = Annotated[DashboardConfig, Depends(owner)]  # noqa: N806 - a type alias for routes

    @app.middleware("http")
    async def headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        if request.url.path != "/dashboard.css":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(NotConfiguredError)
    async def not_configured(_: Request, __: NotConfiguredError) -> HTMLResponse:
        text = "The dashboard has no database, bot or session settings on this deployment."
        return HTMLResponse(pages.message("Not configured", text), status_code=503)

    @app.exception_handler(LoginRequiredError)
    async def login_required(_: Request, __: LoginRequiredError) -> RedirectResponse:
        return RedirectResponse("/login", status_code=303)

    @app.get("/dashboard.css")
    async def stylesheet() -> Response:
        return Response(
            pages.CSS, media_type="text/css", headers={"Cache-Control": "public, max-age=86400"}
        )

    @app.get("/login")
    async def login(
        request: Request, cfg: Annotated[DashboardConfig, Depends(config)]
    ) -> HTMLResponse:
        return HTMLResponse(pages.login(cfg.bot_username, str(request.url_for("auth_telegram"))))

    @app.get("/auth/telegram", name="auth_telegram")
    async def auth_telegram(
        request: Request, cfg: Annotated[DashboardConfig, Depends(config)]
    ) -> Response:
        now = cfg.clock()
        fields = dict(request.query_params)
        if not verify_login(fields, bot_token=cfg.bot_token, owner_id=cfg.owner_id, now=now):
            log.warning("dashboard sign-in refused")
            return HTMLResponse(
                pages.message("Not allowed", "This account cannot open the dashboard."), 403
            )
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            COOKIE,
            issue_session(cfg.owner_id, secret=cfg.session_secret, now=now),
            max_age=int(SESSION_MAX_AGE.total_seconds()),
            httponly=True,
            secure=cfg.secure_cookies,
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/logout")
    async def logout() -> RedirectResponse:
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/")
    async def overview(cfg: Owner) -> HTMLResponse:
        async with cfg.db.session() as session:
            latest = await queries.briefings(session, cfg.owner_id, limit=1)
            health = await queries.health(session, cfg.owner_id, cfg.clock())
        return HTMLResponse(pages.overview(latest[0] if latest else None, health))

    @app.get("/briefings")
    async def briefing_list(cfg: Owner) -> HTMLResponse:
        async with cfg.db.session() as session:
            return HTMLResponse(pages.briefing_list(await queries.briefings(session, cfg.owner_id)))

    @app.get("/briefings/{day}")
    async def briefing_page(day: date, cfg: Owner) -> HTMLResponse:
        async with cfg.db.session() as session:
            detail = await queries.briefing(session, cfg.owner_id, day)
        if detail is None:
            return HTMLResponse(
                pages.message("Not found", "No briefing is stored for that date."), 404
            )
        return HTMLResponse(pages.briefing_page(detail))

    @app.get("/portfolio")
    async def portfolio(cfg: Owner) -> HTMLResponse:
        async with cfg.db.session() as session:
            return HTMLResponse(
                pages.portfolio(await queries.portfolio_history(session, cfg.owner_id))
            )

    @app.get("/signals")
    async def signal_list(cfg: Owner, status: str = "", symbol: str = "") -> HTMLResponse:
        status = status if status in pages.STATUSES else ""
        symbol = symbol.strip()[:24]
        async with cfg.db.session() as session:
            items = await queries.signals(
                session, cfg.owner_id, status=status or None, symbol=symbol or None
            )
        return HTMLResponse(pages.signal_list(items, status, symbol))

    @app.get("/signals/{signal_id}")
    async def signal_page(signal_id: int, cfg: Owner) -> HTMLResponse:
        async with cfg.db.session() as session:
            found = await queries.signal(session, cfg.owner_id, signal_id)
        if found is None:
            return HTMLResponse(pages.message("Not found", "No such signal."), 404)
        return HTMLResponse(pages.signal_page(*found))

    @app.get("/backtests")
    async def report_list(cfg: Owner) -> HTMLResponse:
        async with cfg.db.session() as session:
            return HTMLResponse(pages.report_list(await queries.reports(session)))

    @app.get("/backtests/{report_id}")
    async def report_page(report_id: int, cfg: Owner) -> HTMLResponse:
        async with cfg.db.session() as session:
            detail = await queries.report(session, report_id)
        if detail is None:
            return HTMLResponse(pages.message("Not found", "No such report."), 404)
        return HTMLResponse(pages.report_page(detail))

    @app.get("/health")
    async def health(cfg: Owner) -> HTMLResponse:
        async with cfg.db.session() as session:
            return HTMLResponse(
                pages.health_page(await queries.health(session, cfg.owner_id, cfg.clock()))
            )

    return app


app = create_app()
