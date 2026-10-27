"""Renamed channels, checked by hand for free.

The platform APIs only know a channel's current name. For rows with no result, the job's
"Renamed channels" page links each source channel's page on streamscharts.com (opened in the
user's own browser; the app never contacts the site) and takes the current name the user finds
there. Saving re-checks those rows through the official API, exactly like a ``renamed_to``
value typed in the sheet.
"""

from __future__ import annotations

from itertools import groupby
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.excel.importer import RENAME_CHECK_PLATFORMS
from app.models import JobStatus, ProcessingJob, ProcessingRow, RowStatus
from app.platforms.catalog import PLATFORMS, label
from app.services.jobs import needs_check, recompute_counters, streams_charts_url
from app.workers.queue import enqueue_job

FINISHED = {
    JobStatus.COMPLETED.value,
    JobStatus.PARTIAL.value,
    JobStatus.CANCELLED.value,
    JobStatus.FAILED.value,
}


class RenameError(ValueError):
    pass


def rename_items(db: Session, job: ProcessingJob) -> list[dict[str, Any]]:
    """Rows to look up by hand: no result yet, or a current name already entered."""
    source = str(job.source_platform or "")
    if source not in RENAME_CHECK_PLATFORMS:
        return []
    rows = db.execute(
        select(ProcessingRow)
        .where(ProcessingRow.job_id == job.id, ProcessingRow.source_key.is_not(None))
        .order_by(ProcessingRow.original_row, ProcessingRow.target_platform)
    ).scalars()
    items = []
    for original_row, group in groupby(rows, key=lambda r: r.original_row):
        sibs = list(group)
        first = sibs[0]
        pending = any(not RowStatus(r.status).is_final for r in sibs)
        if not (first.renamed_to or (not pending and needs_check(sibs))):
            continue
        items.append(
            {
                "original_row": original_row,
                "source_value": first.source_value,
                "country": first.country,
                "remarks": first.output_remarks,
                "renamed_to": first.renamed_to,
                "pending": pending,
                "streams_charts_url": streams_charts_url(str(first.source_key), source),
                "results": {
                    str(r.target_platform): r.matched_id if r.decision == "MATCH" else None for r in sibs
                },
                "reason": first.reason,
            }
        )
    return items


def set_renamed_to(
    db: Session, settings: Settings, job: ProcessingJob, entries: list[tuple[int, str | None]]
) -> int:
    """Store the current names the user found and re-check those rows (official API only)."""
    source = str(job.source_platform or "")
    if source not in RENAME_CHECK_PLATFORMS:
        raise RenameError(f"Renamed channels can be checked for Twitch and Kick sheets, not {label(source)}.")
    if job.status not in FINISHED:
        raise RenameError(f"Job is {job.status}; wait for it to finish first.")
    adapter = PLATFORMS[source].adapter
    changed = 0
    for original_row, name in entries:
        name = (name or "").strip() or None
        if name is not None and adapter.normalize_handle(name) is None:
            raise RenameError(f"Row {original_row}: {name!r} is not a valid {label(source)} channel name.")
        rows = list(
            db.execute(
                select(ProcessingRow).where(
                    ProcessingRow.job_id == job.id, ProcessingRow.original_row == original_row
                )
            ).scalars()
        )
        if not rows:
            raise RenameError(f"Row {original_row} is not in this job.")
        if all(r.renamed_to == name for r in rows):
            continue
        for r in rows:
            r.renamed_to = name
            r.status = RowStatus.PENDING.value
            r.error_message = None
        changed += 1
    if changed:
        job.status = JobStatus.QUEUED.value
        job.error_message = None
        job.export_stale = True
        recompute_counters(db, job)
    db.commit()
    if changed:
        enqueue_job(job.id, settings)
    return changed
