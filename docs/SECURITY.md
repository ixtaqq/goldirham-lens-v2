# Security reference

## Access

| Surface | Who can use it | How it is enforced |
| --- | --- | --- |
| Bot commands | The owner, in a private chat with the bot | `bot/updates.py` `is_owner_private` checks user id, chat type and chat id before any handler runs. A test sends every registered command from four kinds of stranger and asserts no reply and no database access. |
| Webhook endpoint | Telegram | `webhook.py` compares the `X-Telegram-Bot-Api-Secret-Token` header with `TELEGRAM_WEBHOOK_SECRET` using `hmac.compare_digest` and returns 401 before parsing the body. |
| One-tap confirmations | The owner, once | A random 16-character token in `pending_actions`, consumed by a single `UPDATE ... WHERE consumed_at IS NULL AND expires_at > now()`. It expires after 15 minutes. |
| Production schema changes | The owner, by approval | Only `migrate.yml` runs migrations, behind the `production` environment's required reviewer. |
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

- `lens.logs` redacts every configured secret value and known secret shapes (Telegram tokens, Anthropic keys, GitHub tokens, database passwords in URLs, Healthchecks URLs) from structured logs, stdlib logs and tracebacks.
- An empty environment value counts as unset, so a missing GitHub secret reads as missing rather than as an empty password.
- gitleaks runs in pre-commit and in CI.

## Database roles

| Role | Used by | Can |
| --- | --- | --- |
| `postgres` | `migrate.yml` | Change the schema |
| `lens_app` | Daily job, webhook | Select, insert, update and delete rows; nothing else |
| `anon`, `authenticated` | Supabase's public API | Nothing; the runbook revokes their grants |

## Workflows

- Every workflow sets `permissions: contents: read` at the top and raises it per job only where needed (`actions: read` for the restore drill, `issues: write` for the drift check).
- Third-party actions are pinned to commit SHAs.
- No workflow uses `pull_request_target`. Scheduled and dispatched jobs run only on `main`.

## Data that leaves the service

| Destination | What is sent |
| --- | --- |
| Market data providers | Ticker symbols and date ranges |
| Telegram | The briefing and command replies, to the owner only |
| Anthropic (only when the narrative is enabled) | The fact catalog: benchmark closes and changes, holding percentage changes, setup levels and sizes. Quantities, entry prices, account values and thesis notes stay out unless the owner opts in. |
| Healthchecks.io | Success and failure pings, with a short error class on failure |

Daily briefings are not uploaded as workflow artifacts, because they contain portfolio values. The database already stores them.

## Showcase

`web/` serves a static export with no secrets, no server code, and no network path to the database, Telegram or GitHub Actions. Its demo data is synthetic.
