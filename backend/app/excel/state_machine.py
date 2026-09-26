"""Explicit row state machine: (source, destination, resolution) -> Excel cell writes.

Implements the tables in docs/DESIGN.md §G exactly. Every combination of inputs maps
to exactly one outcome; unknown combinations raise instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.tables import RowStatus

REMARK_NO_BOTH = "no Id on both platforms"
REMARK_NO_ANY = "no Id on any platform"  # several destinations, none found, source missing too
REMARK_SEPARATOR = "; "


def remark_missing(platform: str) -> str:
    """Remark for a row that has no account on ``platform`` (the Kick wording is historical)."""
    return "no kick id" if platform == "kick" else f"no {platform} id found"


def remark_nearest(platform: str) -> str:
    return f"nearest possible {platform} channel"


def app_remarks(platforms: list[str]) -> set[str]:
    """Every single remark phrase this app can write for these platforms."""
    return {
        REMARK_NO_BOTH,
        REMARK_NO_ANY,
        "nearest possible channel",  # wording used briefly by an earlier version
        *(remark_missing(p) for p in platforms),
        *(remark_nearest(p) for p in platforms),
    }


def is_app_remark(text: Any, platforms: list[str]) -> bool:
    """True if ``text`` was written by this app (possibly several phrases joined by "; ")."""
    if text is None or not str(text).strip():
        return False
    known = app_remarks(platforms)
    return all(part.strip() in known for part in str(text).split(";"))


# Per destination: "match" (confirmed id), "nearest" (only an unconfirmed closest account),
# "none" (nothing on that platform).
LinkState = str


def combine_remarks(source_platform: str, source_exists: bool, links: dict[str, LinkState]) -> str | None:
    """One remark for an Excel row, from the link state of every destination platform.

    With a single destination this is exactly the original two-platform table: empty for a
    confirmed match, "nearest possible <t> channel", "no <t> id found", "no <s> id" (source
    missing) and "no Id on both platforms".
    """
    if not source_exists:
        missing = [t for t, state in links.items() if state == "none"]
        if len(missing) == len(links):
            return REMARK_NO_BOTH if len(links) == 1 else REMARK_NO_ANY
        return REMARK_SEPARATOR.join([remark_missing(source_platform), *(remark_missing(t) for t in missing)])
    parts = [
        remark_nearest(t) if state == "nearest" else remark_missing(t)
        for t, state in links.items()
        if state != "match"
    ]
    return REMARK_SEPARATOR.join(parts) or None


def remark_write(remark: str | None, existing_remarks: Any, platforms: list[str]) -> bool:
    """Never erase a user's own note; only fill blanks or replace/clear our own phrases."""
    existing_is_ours = is_app_remark(existing_remarks, platforms)
    if remark is not None:
        return is_blank(existing_remarks) or existing_is_ours
    return existing_is_ours or (existing_remarks is not None and is_blank(existing_remarks))


EMPTY_PLACEHOLDERS = {"", "none", "null", "nan", "n/a", "na", "-", "--", "unknown", "not found"}


def is_blank(value: Any) -> bool:
    return value is None or str(value).strip().lower() in EMPTY_PLACEHOLDERS


@dataclass(frozen=True)
class RowOutcome:
    status: RowStatus
    destination: str | None  # value to write (None = empty cell)
    remarks: str | None  # value to write (None = empty cell)
    write_destination: bool
    write_remarks: bool
    case: str  # e.g. "KICK_A" — for audit/debugging
    link: LinkState = "none"  # this destination's contribution to the row's remark
    source_exists: bool = False


# (source_status, decision, target_status) -> (case, write the matched id?)
_TABLE: dict[tuple[str, str, str | None], tuple[str, bool]] = {
    ("EXISTS", "MATCH", None): ("A", True),
    ("EXISTS", "REVIEW", None): ("B", False),
    ("EXISTS", "NO_MATCH", None): ("B", False),
    ("NOT_FOUND", "MATCH", "VERIFIED"): ("C", True),
    ("NOT_FOUND", "REVIEW", "EXISTS_UNVERIFIED"): ("C2", False),
    ("NOT_FOUND", "NO_MATCH", "EXISTS_UNVERIFIED"): ("C2", False),
    ("NOT_FOUND", "NO_MATCH", "NOT_FOUND"): ("D", False),
}


def has_target_link(resolution: dict[str, Any]) -> bool:
    """Is there a best destination account to link — the match, the review candidate, or any
    candidate not rejected in review? (same rule as the link columns)"""
    return bool(resolution.get("matched_id") or resolution.get("review_candidate")) or any(
        c.get("username") and c.get("manual_verdict") != "REJECTED"
        for c in resolution.get("candidates") or []
    )


class StateMachineError(ValueError):
    pass


def transition(
    source_platform: str,
    target_platform: str,
    resolution: dict[str, Any],
    existing_destination: Any = None,
    existing_remarks: Any = None,
    policy: str = "preserve",
) -> RowOutcome:
    source_status = resolution.get("source_status")
    decision = resolution.get("decision")
    target_status = resolution.get("target_status") if source_status == "NOT_FOUND" else None
    key = (str(source_status), str(decision), target_status)
    if key not in _TABLE:
        raise StateMachineError(f"undefined state {(source_platform, *key)}")
    letter, write_id = _TABLE[key]
    case = f"{source_platform.upper()}_{letter}"
    source_exists = source_status == "EXISTS"
    link = "match" if write_id else ("nearest" if has_target_link(resolution) else "none")
    remark = combine_remarks(source_platform, source_exists, {target_platform: link})

    matched = resolution.get("matched_id")
    if write_id and not matched:
        raise StateMachineError(f"state {case} requires a matched id")
    destination = str(matched) if write_id else None

    if source_status == "NOT_FOUND":
        status = RowStatus.MATCH if write_id else RowStatus.SOURCE_NOT_FOUND
    else:
        status = {"MATCH": RowStatus.MATCH, "REVIEW": RowStatus.REVIEW, "NO_MATCH": RowStatus.NO_MATCH}[
            str(decision)
        ]

    # Existing destination values in the upload are user data.
    if not is_blank(existing_destination):
        if policy == "preserve":
            return RowOutcome(
                RowStatus.PRESERVED, None, None, False, False, case + "_PRESERVED", "preserved", source_exists
            )
        # overwrite policy: replace only with a verified id; never erase user data on no-match
        write_dest = destination is not None
    else:
        # write the matched id, or turn a placeholder such as "None" into a genuinely empty cell
        write_dest = destination is not None or existing_destination is not None

    write_rem = remark_write(remark, existing_remarks, [source_platform, target_platform])
    return RowOutcome(status, destination, remark, write_dest, write_rem, case, link, source_exists)


def error_outcome(status: RowStatus) -> RowOutcome:
    """Errors never touch the workbook."""
    assert status.is_error
    return RowOutcome(status, None, None, False, False, "ERROR")


def empty_source_outcome() -> RowOutcome:
    return RowOutcome(RowStatus.SKIPPED_EMPTY, None, None, False, False, "EMPTY_SOURCE")
