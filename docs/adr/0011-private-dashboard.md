# 0011. Private dashboard rendered by Python behind Telegram sign-in

Status: accepted, 2026-10-17. Not yet deployed; deployment needs the owner's accounts.

## Context

The build prompt's optional Phase 13 asks for an owner-only dashboard with five views: briefing archive, portfolio history, signal explorer, backtest reports and health. It must sit behind owner authentication, read through a read-only role, and never hand credentials to the browser.

The data and its formatting rules already live in Python: the storage repositories, the Telegram renderer's number formats and the backtest report.

## Decision

- **Python, rendered on the server.** `lens.dashboard` is a FastAPI app that queries through SQLAlchemy and formats every figure with `lens.delivery.format`, as the briefing does. Pages are plain HTML and a small stylesheet. The only script is Telegram's login widget on the sign-in page.
- **Sign-in.** The Telegram Login Widget redirects to `/auth/telegram`. The server checks Telegram's HMAC-SHA256 signature (keyed by SHA-256 of the bot token), the owner's id and a signature under 10 minutes old. It then sets a 12-hour HttpOnly, SameSite=Lax cookie signed with `DASHBOARD_SESSION_SECRET`. Every other page redirects to sign-in.
- **Read-only twice over.** The dashboard connects as `lens_dashboard`, which has only `SELECT`, and runs each request inside `SET TRANSACTION READ ONLY` that it rolls back.
- **Separate project, shared code.** `api/dashboard.py` sits beside `api/telegram.py` in one `vercel.json`. The owner creates a second Vercel project from the same repository and gives it only the dashboard's variables. On the webhook's project the dashboard answers 503, because its variables are absent. On the dashboard's project the webhook stops before reading any update, because its secret and database URL are absent.
- `import-linter` keeps `lens.dashboard` away from the data layer, pipeline, narrative, bot and outbound HTTP.

## Consequences

- A figure on the dashboard is formatted by the same code as the same figure in Telegram.
- Tests cover the sign-in rules, a walk of every route with no cookie, a forged cookie and another user's cookie, a stranger whom Telegram has signed, only `/logout` accepting POST, owner scoping, and a write attempt refused by the read-only transaction.
- Two things are unverified until the first deploy. One is that the catch-all rewrite reaches the FastAPI routes with their original paths. The other is that Telegram accepts the domain set with BotFather `/setdomain`.
- Both Vercel projects run both functions. Each is inert where its variables are missing, which is simpler than splitting the repository, but it means each project's variables must be set exactly as the runbook lists them.
