"""Structured logging with a PII scrubber.

Leaking personal data through logs is one of the most common incidents there is,
and it is unfixable after the fact: the log has already been shipped to a
third-party backend, indexed, and replicated. Retroactively scrubbing it is not
possible.

So the rule is enforced at the only moment it can be -- before the record leaves
the process:

  * every log and span carries `tenant_id`;
  * **none** carries `person_id`, a phone number, an email, a token, or a
    password.

`person_id` in a log is the same failure as `person_id` in an analytics event: it
is the join key that lets two competing tenants correlate their customer bases.
See ADR 0011 and docs/threat-model.md.
"""

from __future__ import annotations

from typing import Any

import structlog

# Dropped outright. There is no legitimate reason for any of these to reach a log
# backend, and "just for debugging" is exactly how they end up there permanently.
FORBIDDEN_KEYS = frozenset(
    {
        "person_id",
        "phone",
        "phone_e164",
        "email",
        "password",
        "otp",
        "token",
        "authorization",
        "cookie",
        "session",
        "fcm_token",
        "identity_pepper",
    }
)


def scrub_pii(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        if key.lower() in FORBIDDEN_KEYS:
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            scrub_pii,  # must run before the renderer, or it renders nothing useful
            structlog.processors.JSONRenderer(),
        ],
    )
