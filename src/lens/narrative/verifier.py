"""Placeholder grounding. Any number the model writes itself rejects the whole narrative."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import StrEnum

from lens.domain.facts import Fact, FactScope
from lens.narrative.schema import CAVEATS, AssetNote, NarrativeOutput

PLACEHOLDER = re.compile(r"\{\{f:([^{}\s]+)\}\}")
MAX_SENTENCE = 240
MAX_SENTENCES = 12
NUMBER_WORDS = frozenset(
    {
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "tens",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "hundreds",
        "thousand",
        "thousands",
        "million",
        "millions",
        "billion",
        "billions",
        "trillion",
        "trillions",
        "percent",
        "percentage",
        "half",
        "halves",
        "halved",
        "double",
        "doubled",
        "twice",
        "triple",
        "tripled",
        "quadrupled",
        "quarter",
        "third",
        "thirds",
        "dozen",
        "dozens",
    }
)
CURRENCY = re.compile(r"[$€£¥₹]|\b(?:usd|myr|rm|us\$|usdt|eur|gbp|sgd)\b", re.IGNORECASE)
BANNED = (
    "buy now",
    "sell now",
    "you should buy",
    "you should sell",
    "must buy",
    "must sell",
    "guaranteed",
    "guarantee",
    "will rise",
    "will fall",
    "will go up",
    "will go down",
    "can't lose",
    "cannot lose",
    "risk-free",
    "risk free",
    "sure thing",
    "to the moon",
)


class Rejection(StrEnum):
    UNGROUNDED_NUMBER = "ungrounded_number"
    UNKNOWN_FACT = "unknown_fact"
    WRONG_SCOPE = "wrong_scope"
    WRONG_SUBJECT = "wrong_subject"
    UNKNOWN_SYMBOL = "unknown_symbol"
    BANNED_PHRASE = "banned_phrase"
    TOO_LONG = "too_long"
    EMPTY = "empty"


class VerificationError(ValueError):
    def __init__(self, rejection: Rejection, detail: str) -> None:
        super().__init__(f"{rejection}: {detail}")
        self.rejection = rejection


def _check(
    text: str,
    *,
    facts: Mapping[str, Fact],
    scope: FactScope,
    subject: str | None,
    allowed_words: Iterable[str],
) -> str:
    if len(text) > MAX_SENTENCE:
        raise VerificationError(Rejection.TOO_LONG, text[:40])
    lowered = text.lower()
    for phrase in BANNED:
        if phrase in lowered:
            raise VerificationError(Rejection.BANNED_PHRASE, phrase)

    def substitute(match: re.Match[str]) -> str:
        fact = facts.get(match.group(1))
        if fact is None:
            raise VerificationError(Rejection.UNKNOWN_FACT, match.group(1))
        if fact.scope is not scope:
            raise VerificationError(Rejection.WRONG_SCOPE, match.group(1))
        if subject is not None and fact.subject != subject:
            raise VerificationError(Rejection.WRONG_SUBJECT, match.group(1))
        return fact.rendered()

    stripped = PLACEHOLDER.sub(" ", text)
    for word in allowed_words:
        stripped = stripped.replace(word, " ")
    if re.search(r"[\d%％‰]", stripped) or CURRENCY.search(stripped):
        raise VerificationError(Rejection.UNGROUNDED_NUMBER, text[:60])
    words = set(re.findall(r"[a-z]+", stripped.lower()))
    numeric = {w for w in words if w in NUMBER_WORDS or w.removesuffix("fold") in NUMBER_WORDS}
    if numeric:
        raise VerificationError(Rejection.UNGROUNDED_NUMBER, ", ".join(sorted(numeric)))
    return PLACEHOLDER.sub(substitute, text).strip()


def verify(
    output: NarrativeOutput,
    facts: Mapping[str, Fact],
    *,
    holdings: Mapping[str, str],
    setups: Mapping[str, str],
    names: Mapping[str, str],
) -> list[str]:
    """Return the final paragraphs with every placeholder replaced by Python's rendering."""
    total = len(output.market) + sum(len(n.sentences) for n in (*output.holdings, *output.setups))
    if total == 0:
        raise VerificationError(Rejection.EMPTY, "no sentences")
    if total > MAX_SENTENCES:
        raise VerificationError(Rejection.TOO_LONG, f"{total} sentences")
    allowed = sorted({*names, *names.values()}, key=len, reverse=True)
    paragraphs = []
    if output.market:
        paragraphs.append(
            " ".join(
                _check(s, facts=facts, scope=FactScope.MARKET, subject=None, allowed_words=allowed)
                for s in output.market
            )
        )

    def notes(items: list[AssetNote], known: Mapping[str, str], scope: FactScope) -> None:
        for note in items:
            if note.symbol not in known:
                raise VerificationError(Rejection.UNKNOWN_SYMBOL, note.symbol)
            body = " ".join(
                _check(s, facts=facts, scope=scope, subject=note.symbol, allowed_words=allowed)
                for s in note.sentences
            )
            if body:
                paragraphs.append(f"{known[note.symbol]}: {body}")

    notes(list(output.holdings), holdings, FactScope.HOLDING)
    notes(list(output.setups), setups, FactScope.SETUP)
    paragraphs.append(CAVEATS[output.caveat])
    return paragraphs
