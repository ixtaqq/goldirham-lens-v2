# 0009. Call the Telegram Bot API directly with httpx

Status: accepted, 2026-10-16.

## Context

v1 used `python-telegram-bot`, which is built around a long-running application with its own update loop. This project has no long-running process. The webhook handles one update per request, and the daily job sends a few messages and exits.

## Decision

`delivery/telegram.py` calls the Bot API over `httpx`. It uses five methods. `sendMessage` and `answerCallbackQuery` serve the briefing and commands, `setWebhook` registers the webhook, and `getMe` and `getWebhookInfo` back `lens doctor`. Errors map to typed exceptions. A connection error before the request was sent counts as "certainly not delivered". A timeout counts as "maybe delivered", which moves the delivery to `HELD`.

## Consequences

- The webhook bundle stays small, and cold starts are short.
- The delivery state machine controls retries. No library retries a send behind its back, which could duplicate a chunk.
- New Bot API features need a few lines of code each, instead of a library upgrade.
