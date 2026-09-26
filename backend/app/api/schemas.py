from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    status: str
    source_platform: str | None
    detected_platform: str | None
    detection_note: str | None
    sheet_name: str | None
    header_row: int | None
    total_rows: int
    processed_rows: int
    match_count: int
    no_match_count: int
    review_count: int
    not_found_count: int
    error_count: int
    skipped_count: int
    error_message: str | None
    warnings_json: list[str] | None
    verification_json: dict[str, Any] | None
    export_stale: bool
    matching_engine_version: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    output_available: bool = False
    output_filename: str | None = None
    review_filename: str | None = None
    needs_platform_choice: bool = False
    target_platforms: list[str] = []
    platforms: list[str] = []  # platforms with an id column in the sheet
    source_options: list[str] = []  # id columns that actually contain ids (possible inputs)


class StartRequest(BaseModel):
    source_platform: str | None = None
    target_platforms: list[str] | None = None  # search several platforms at once


class CredentialsIn(BaseModel):
    values: dict[str, str]


class RowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    original_row: int
    target_platform: str | None
    source_value: str | None
    country: str | None
    existing_destination: str | None
    status: str
    source_status: str | None
    target_status: str | None
    decision: str | None
    confidence: float | None
    matched_id: str | None
    review_candidate: str | None
    output_destination: str | None
    output_remarks: str | None
    write_destination: bool
    write_remarks: bool
    reason: str | None
    error_message: str | None
    manual_verdict: str | None
    attempts: int


class RowDetail(RowOut):
    evidence_json: dict[str, Any] | None


class RowPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[RowOut]


class ReviewSubmit(BaseModel):
    original_row: int
    target_platform: str | None = None
    verdict: Literal["CONFIRM", "REJECT", "SKIP"]
    target_username: str | None = None
    note: str | None = None
