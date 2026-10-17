# Runbook

How to set up Goldirham Lens from nothing, keep it running, and recover when something breaks. Every step that touches money, real messages or the production database is marked. Do those yourself.

## Set it up the first time

You need a GitHub account, a Telegram account, and free accounts at Supabase, Vercel, Healthchecks.io and Alpha Vantage. All of them have a free tier that covers this project. Check each one's current limits before you rely on them.

### 1. Create the repository

1. Create a **private** GitHub repository. GitHub turns off scheduled workflows in public repositories after 60 days without activity.
2. Push this code to its `main` branch.
3. In **Settings > Environments**, create an environment named `production` and add yourself as a required reviewer. Every migration waits for your approval there.

### 2. Create the Telegram bot

1. In Telegram, open @BotFather, send `/newbot`, and follow the prompts. Keep the token it returns.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<token>/getUpdates` in a browser. The number at `message.from.id` is your owner id.

### 3. Create the database

1. Create a Supabase project in the region closest to you (Singapore for Malaysia).
2. In **Project Settings > Database > Connection string**, copy two strings:
   - The **Session pooler** string (port 5432). GitHub runners reach Supabase over IPv4, and the direct connection is IPv6 only, so the workflows use this one.
   - The **Transaction pooler** string (port 6543). The Vercel webhook uses this one.
3. In the SQL editor, create the application role and keep Supabase's public API away from the tables:

   ```sql
   create role lens_app login password '<a long random password>';
   grant usage on schema public to lens_app;
   alter default privileges for role postgres in schema public
     grant select, insert, update, delete on tables to lens_app;
   alter default privileges for role postgres in schema public
     grant usage, select on sequences to lens_app;
   revoke all on schema public from anon, authenticated;
   alter default privileges for role postgres in schema public revoke all on tables from anon, authenticated;
   ```

   Migrations run as `postgres`. The daily job and the webhook connect as `lens_app`, which cannot drop or alter tables. On the Supabase pooler, the user name has the form `lens_app.<project-ref>`.

### 4. Create the monitoring checks

In Healthchecks.io, create three checks. Connect its Telegram integration so alerts reach you even when this project is down.

| Check | Schedule (cron, UTC) | Grace | Secret |
| --- | --- | --- | --- |
| Daily briefing | `0 23 * * *` | 75 minutes | `HEALTHCHECK_PING_URL` |
| Nightly backup | `15 18 * * *` | 60 minutes | `HEALTHCHECK_BACKUP_URL` |
| Restore drill | `30 19 * * 0` | 120 minutes | `HEALTHCHECK_DRILL_URL` |

The daily check alerts at 08:15 MYT if no successful run has pinged.

### 5. Create the backup key

1. Install `age` and run `age-keygen -o lens-backup.key`.
2. The line starting `# public key:` is `AGE_RECIPIENT`. The whole file is `AGE_IDENTITY`.
3. Store a copy of `lens-backup.key` offline. Without it, no backup can be restored.

### 6. Add the GitHub secrets

In **Settings > Secrets and variables > Actions**, add repository secrets:

| Secret | Value |
| --- | --- |
| `DATABASE_URL_DIRECT` | Session pooler string with the `lens_app` user |
| `TELEGRAM_BOT_TOKEN` | From BotFather |
| `OWNER_TELEGRAM_ID` | Your owner id |
| `HEALTHCHECK_PING_URL`, `HEALTHCHECK_BACKUP_URL`, `HEALTHCHECK_DRILL_URL` | From Healthchecks.io |
| `ALPHA_VANTAGE_API_KEY` | Free key from alphavantage.co; without it, US assets stay single-source and get no setups |
| `AGE_RECIPIENT`, `AGE_IDENTITY` | From step 5 |
| `ANTHROPIC_API_KEY` | Only if you enable the narrative later |

In the `production` environment, add one more secret, `DATABASE_URL_MIGRATOR`. Its value is the session pooler string with the `postgres` user.

### 7. Create the schema

Run **Actions > Migrate production schema** with `migrate` typed in the box. It takes a backup first, then waits for your approval, then runs `alembic upgrade head`. **This changes the production database.**

### 8. Deploy the webhook

1. In Vercel, import the repository as a new project. Keep the root directory as the repository root and the framework preset as **Other**.
2. Add environment variables: `DATABASE_URL_POOLED` (transaction pooler string, `lens_app` user), `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID`, `TELEGRAM_WEBHOOK_SECRET` (a long random string), and, for `/run` and `/watchlist add`, `GITHUB_DISPATCH_TOKEN` and `GITHUB_REPOSITORY` (`owner/name`). The dispatch token is a fine-grained token for this one repository with **Actions: write**.
3. Deploy, then register the webhook from your machine. **This changes the bot's live configuration.**

   ```powershell
   $env:TELEGRAM_BOT_TOKEN = "<token>"
   $env:TELEGRAM_WEBHOOK_SECRET = "<the same secret>"
   python -m uv run lens webhook set https://<project>.vercel.app/api/telegram
   ```

4. Send `/start` to the bot. It answers in a few seconds.

### 9. Send the first briefing

Run **Actions > Daily briefing > Run workflow**. **This sends a real Telegram message.** The briefing arrives within a few minutes. From the next morning on, it arrives every day before 08:00 MYT.

### 10. Decide whether a strategy goes live

No strategy is live until you activate a version that has a backtest report. The briefing says so in its data status.

```powershell
python -m uv run lens backtest
python -m uv run lens strategy list
python -m uv run lens strategy activate pullback_in_uptrend <version>
```

Read the report first. The first report found that the v1 rules did not beat random entries with the same stops and targets ([ADR 0005](adr/0005-backtest-and-activation.md)). Activating anyway is your call.

### 11. Publish the showcase

Create a second Vercel project from the same repository with the root directory set to `web`. It needs no environment variables and never connects to anything.

## Daily operations

| Time (MYT) | What runs | What you see |
| --- | --- | --- |
| 02:15 | `backup.yml` | Nothing, unless it fails |
| 07:00 | `daily.yml` first trigger | The briefing |
| 07:40 | `daily.yml` second trigger | Nothing; it finds the day done |
| 08:15 | Healthchecks deadline | An alert only if no briefing went out |
| 17:45 weekdays | `alerts.yml` | An EXIT or REDUCE review alert, only in immediate mode |
| Monday 03:30 | `restore-drill.yml` | Nothing, unless the drill fails |
| Saturday 10:00 | `provider-drift.yml` | A GitHub issue, only if a provider changed |

Check the service any time with `/health`, or locally:

```powershell
python -m uv run lens doctor
```

## Recover from a problem

### No briefing arrived

1. Open the Healthchecks alert or **Actions > Daily briefing** and read the failed run's log.
2. Send `/run` to the bot, or run the workflow by hand. The day's lock means you cannot get two briefings.

### A briefing is held

A timeout after some messages were sent leaves the briefing held, so you never get duplicates without choosing to. Send `/held`, read the preview, then tap **Resend remaining** or **Dismiss**.

### An asset shows "a session inside the required window is missing"

Run `python -m uv run lens readiness`. If it reports a calendar check where every asset of one market lacks the same day, the exchange was closed that day and `exchange_calendars` does not know. Confirm the day on the exchange's own holiday list, add it under `calendar_holidays` in `config/settings.yaml`, and push.

### The database schema is behind the code

The briefing arrives in degraded form and says so. Run **Actions > Migrate production schema** and approve it.

### Restore from a backup

**This replaces production data. Do it only after the restore drill on that backup has passed.**

1. Download the `lens-backup` artifact from a successful **Nightly backup** run.
2. Check it: `sha256sum -c SHA256SUMS`.
3. Decrypt it: `age -d -i lens-backup.key -o lens.dump lens.dump.age`.
4. Restore it into a new Supabase project with `pg_restore --no-owner --no-privileges --dbname "<session pooler URL>" lens.dump`.
5. Point the secrets at the new project and run `lens doctor`.

### Rotate a secret

Change it at its source (BotFather `/revoke`, Supabase password reset, a new Healthchecks URL), update the GitHub secret or Vercel variable, and run `lens doctor`. For the bot token, run `lens webhook set` again.
