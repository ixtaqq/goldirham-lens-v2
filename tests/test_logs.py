from __future__ import annotations

import io
import json
import logging

import pytest

from lens.logs import REDACTED, Redactor, configure_logging, get_logger

CONFIGURED_SECRET = "s3cr3t-value-from-env-123"
SPLIT_TOKEN = "987654321" + ":" + "AAH" + "x" * 32


def test_configured_secret_value_never_reaches_structured_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging([CONFIGURED_SECRET])
    get_logger("test").info(
        "connecting", detail=f"key={CONFIGURED_SECRET}", nested={"a": [CONFIGURED_SECRET]}
    )

    line = capsys.readouterr().err.strip().splitlines()[-1]
    record = json.loads(line)
    assert CONFIGURED_SECRET not in line
    assert record["detail"] == f"key={REDACTED}"
    assert record["nested"] == {"a": [REDACTED]}


def test_secret_in_exception_traceback_is_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging([CONFIGURED_SECRET])
    try:
        raise RuntimeError(f"failed with {CONFIGURED_SECRET}")
    except RuntimeError:
        get_logger("test").exception("boom")

    output = capsys.readouterr().err
    assert CONFIGURED_SECRET not in output
    assert REDACTED in output


def test_stdlib_loggers_from_dependencies_are_redacted() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logging.getLogger().addHandler(handler)
    try:
        configure_logging([CONFIGURED_SECRET])
        logging.getLogger("some.dependency").warning(
            "calling https://api.telegram.org/bot%s/send with %s", SPLIT_TOKEN, CONFIGURED_SECRET
        )
    finally:
        logging.getLogger().removeHandler(handler)

    output = stream.getvalue()
    assert SPLIT_TOKEN not in output
    assert CONFIGURED_SECRET not in output
    assert "api.telegram.org/bot[REDACTED]/send with [REDACTED]" in output


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"token {SPLIT_TOKEN}", f"token {REDACTED}"),
        (
            "postgresql+asyncpg://lens:hunter2pass@db.example:5432/lens",
            "postgresql+asyncpg://lens:[REDACTED]@db.example:5432/lens",
        ),
        ("ping https://hc-ping.com/1234abcd-11aa", f"ping {REDACTED}"),
        ("key sk-ant-api03-abcdefghijk", f"key {REDACTED}"),
        ("nothing secret here", "nothing secret here"),
    ],
)
def test_known_secret_shapes_are_redacted(text: str, expected: str) -> None:
    assert Redactor().redact(text) == expected
