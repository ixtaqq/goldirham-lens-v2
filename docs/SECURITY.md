# Security reference

## Access

| Surface | Who can use it | How it is enforced |
| --- | --- | --- |
| Bot commands | The owner, in a private chat with the bot | `bot/updates.py` `is_owner_private` checks user id, chat type and chat id before any handler runs. A test sends every registered command from four kinds of stranger and asserts no reply and no database access. |
| Webhook endpoint | Telegram | `webhook.py` compares the `X-Telegram-Bot-Api-Secret-Token` header with `TELEGRAM_WEBHOOK_SECRET` using `hmac.compare_digest` and returns 401 before parsing the body. |
| One-tap confirmations | The owner, once | A random 16-character token in `pending_actions`, consumed by a single `UPDATE ... WHERE consumed_at IS NULL AND expires_at > now()`. It expires after 15 minutes. |
| Production schema changes | The owner, by approval | Only `migrate.yml` runs migrations, behind the `production` environment's required reviewer. |
| Private dashboard | The owner, after Telegram sign-in | `dashboard/auth.py` checks Telegram's HMAC-SHA256 signature (keyed by SHA-256 of the bot token), requires the owner's id and a signature under 10 minutes old, then sets an HttpOnly, SameSite=Lax cookie signed with `DASHBOARD_SESSION_SECRET` for 12 hours. Every other page redirects to sign-in, and a test walks every route with no cookie, a forged cookie and another user's cookie. |
| Restore drills | The job-local database | `ops/backup.py` `ensure_drill_target` refuses any host other than localhost, any database other than `lens_drill` after percent-decoding, and URL parameters that redirect the connection. |

## Secrets

| Secret | Stored in | Read by |
| --- | --- | --- |
| `DATABASE_URL_DIRECT` | GitHub secret | daily, backfill, backup, alerts, restore drill |
| `DATABASE_URL_MIGRATOR` | GitHub `production` environment | migrate |
| `DATABASE_URL_POOLED` | Vercel | webhook |
| `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID` | GitHub and Vercel | daily, alerts, backfill, webhook |
| `TELEGRAM_WEBHOOK_SECRET`, `GITHUB_DISPATCH_TOKEN` | Vercel | webhook |
| `HEALTHCHECK_*_URL` | GitHub | daily, backup, restore drill |
| `ALPHA_VANTAGE_API_KEY`, `ANTHROPIC_API_KEY` | GitHub | daily, backfill, alerts |
| `AGE_RECIPIENT` | GitHub | backup |
| `AGE_IDENTITY` | GitHub, read only in the restore-drill job, plus an offline copy | restore drill |
| `DASHBOARD_DATABASE_URL`, `DASHBOARD_SESSION_SECRET`, `TELEGRAM_BOT_USERNAME` | The dashboard's own Vercel project | dashboard |

- `lens.logs` redacts every configured secret value and known secret shapes (Telegram tokens, Anthropic keys, GitHub tokens, database passwords in URLs, Healthchecks URLs) from structured logs, stdlib logs and tracebacks.
- An empty environment value counts as unset, so a missing GitHub secret reads as missing rather than as an empty password.
- gitleaks runs in pre-commit and in CI.

## Database roles

| Role | Used by | Can |
| --- | --- | --- |
| `postgres` | `migrate.yml` | Change the schema |
| `lens_app` | Daily job, webhook | Select, insert, update and delete rows; nothing else |
| `lens_dashboard` | Dashboard | Select only. The dashboard also runs every request inside `SET TRANSACTION READ ONLY` and rolls it back. |
| `anon`, `authenticated` | Supabase's public API | Nothing; the runbook revokes their grants |

## Workflows

- Every workflow sets `permissions: contents: read` at the top and raises it per job only where needed (`actions: read` for the restore drill, `issues: write` for the drift check).
- Third-party actions are pinned to commit SHAs.
- No workflow uses `pull_request_target`. The daily briefing and holding alerts run only on `main`.
- Cron runs of the five scheduled workflows skip unless the repository variable `SCHEDULES_ENABLED` is `true`.

## Data that leaves the service

| Destination | What is sent |
| --- | --- |
| Market data providers | Ticker symbols and date ranges |
| Telegram | The briefing and command replies, to the owner only |
| Anthropic (only when the narrative is enabled) | The fact catalog: benchmark closes and changes, holding percentage changes, setup levels and sizes. Quantities, entry prices, account values and thesis notes stay out unless the owner opts in. |
| Healthchecks.io | Success and failure pings, with a short error class on failure |

Daily briefings are not uploaded as workflow artifacts, because they contain portfolio values. The database already stores them.

## Dashboard pages

The dashboard renders HTML on the server. Pages carry no secrets, are sent with `Cache-Control: no-store` and `X-Robots-Tag: noindex`, and use a Content Security Policy that allows only Telegram's login script and frame. Stored Telegram text is re-escaped so only bold, italic and code markup survives.

## Showcase

`web/` serves a static export with no secrets, no server code, and no network path to the database, Telegram or GitHub Actions. Its demo data is synthetic.
