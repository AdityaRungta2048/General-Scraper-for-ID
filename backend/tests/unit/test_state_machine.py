import pytest

from app.excel.state_machine import (
    REMARK_NO_BOTH,
    StateMachineError,
    error_outcome,
    remark_missing,
    remark_source_missing,
    transition,
)
from app.models.tables import RowStatus

REMARK_NO_KICK = remark_missing("kick")
REMARK_NO_TWITCH = remark_missing("twitch")


def res(source_status, decision, target_status=None, matched="Target_1", candidates=(), review=None):
    return {
        "source_status": source_status,
        "decision": decision,
        "target_status": target_status,
        "matched_id": matched if decision == "MATCH" else None,
        "review_candidate": review,
        "candidates": [{"username": c} for c in candidates],
    }


# ------------------------------------------------------------------ Kick source
@pytest.mark.parametrize(
    ("resolution", "dest", "remark", "status", "case"),
    [
        (res("EXISTS", "MATCH"), "Target_1", None, RowStatus.MATCH, "KICK_A"),
        (res("EXISTS", "REVIEW", review="cand"), None, REMARK_NO_TWITCH, RowStatus.REVIEW, "KICK_B"),
        (
            res("EXISTS", "NO_MATCH", candidates=["closest"]),
            None,
            REMARK_NO_TWITCH,
            RowStatus.NO_MATCH,
            "KICK_B",
        ),
        (res("EXISTS", "NO_MATCH"), None, REMARK_NO_TWITCH, RowStatus.NO_MATCH, "KICK_B"),
        (
            res("NOT_FOUND", "MATCH", "VERIFIED"),
            "Target_1",
            remark_source_missing("kick"),
            RowStatus.MATCH,
            "KICK_C",
        ),
        (
            res("NOT_FOUND", "REVIEW", "EXISTS_UNVERIFIED", review="same"),
            None,
            REMARK_NO_BOTH,
            RowStatus.SOURCE_NOT_FOUND,
            "KICK_C2",
        ),
        (
            res("NOT_FOUND", "NO_MATCH", "NOT_FOUND"),
            None,
            REMARK_NO_BOTH,
            RowStatus.SOURCE_NOT_FOUND,
            "KICK_D",
        ),
    ],
)
def test_kick_source_table(resolution, dest, remark, status, case):
    out = transition("kick", "twitch", resolution)
    assert (out.destination, out.remarks, out.status, out.case) == (dest, remark, status, case)


# ------------------------------------------------------------------ Twitch source
@pytest.mark.parametrize(
    ("resolution", "dest", "remark", "case"),
    [
        (res("EXISTS", "MATCH"), "Target_1", None, "TWITCH_A"),
        (res("EXISTS", "REVIEW", review="cand"), None, REMARK_NO_KICK, "TWITCH_B"),
        (res("EXISTS", "NO_MATCH", candidates=["closest"]), None, REMARK_NO_KICK, "TWITCH_B"),
        (res("EXISTS", "NO_MATCH"), None, REMARK_NO_KICK, "TWITCH_B"),
        (res("NOT_FOUND", "NO_MATCH", "NOT_FOUND"), None, REMARK_NO_BOTH, "TWITCH_D"),
        (res("NOT_FOUND", "REVIEW", "EXISTS_UNVERIFIED", review="same"), None, REMARK_NO_BOTH, "TWITCH_C2"),
        (res("NOT_FOUND", "MATCH", "VERIFIED"), "Target_1", "no twitch channel found", "TWITCH_C"),
    ],
)
def test_twitch_source_table(resolution, dest, remark, case):
    out = transition("twitch", "kick", resolution)
    assert (out.destination, out.remarks, out.case) == (dest, remark, case)


def test_unmatched_candidate_is_never_offered_as_nearest_channel():
    out = transition("twitch", "kick", res("EXISTS", "NO_MATCH", candidates=["somekick"]))
    assert out.remarks == REMARK_NO_KICK and out.destination is None


def test_exact_remark_phrases():
    assert REMARK_NO_KICK == "no kick id"
    assert REMARK_NO_TWITCH == "no twitch id found"
    assert remark_source_missing("twitch") == "no twitch channel found"
    assert REMARK_NO_BOTH == "no Id on both platforms"


def test_undefined_states_raise_instead_of_guessing():
    with pytest.raises(StateMachineError):
        transition("kick", "twitch", {"source_status": "EXISTS", "decision": "MAYBE"})
    with pytest.raises(StateMachineError):
        transition(
            "kick",
            "twitch",
            {"source_status": "NOT_FOUND", "decision": "MATCH", "target_status": "NOT_FOUND"},
        )
    with pytest.raises(StateMachineError):  # MATCH without an id is impossible
        transition("kick", "twitch", {"source_status": "EXISTS", "decision": "MATCH", "matched_id": None})


def test_errors_never_write():
    out = error_outcome(RowStatus.TEMPORARY_ERROR)
    assert not out.write_destination and not out.write_remarks


def test_existing_destination_preserved_by_default():
    out = transition("kick", "twitch", res("EXISTS", "MATCH"), existing_destination="SomeoneTyped")
    assert out.status == RowStatus.PRESERVED and not out.write_destination and not out.write_remarks


def test_overwrite_policy_only_replaces_with_verified_id():
    out = transition("kick", "twitch", res("EXISTS", "MATCH"), existing_destination="old", policy="overwrite")
    assert out.write_destination and out.destination == "Target_1"
    out2 = transition(
        "kick", "twitch", res("EXISTS", "NO_MATCH"), existing_destination="old", policy="overwrite"
    )
    assert not out2.write_destination  # never erase user data on a no-match


def test_unconfirmed_candidate_is_never_written():
    r = res("EXISTS", "REVIEW", candidates=["maybe"], review="maybe")
    out = transition("twitch", "kick", r)
    assert out.destination is None and out.remarks == REMARK_NO_KICK


def test_placeholder_none_becomes_genuinely_empty():
    out = transition("twitch", "kick", res("EXISTS", "NO_MATCH"), existing_destination="None")
    assert out.write_destination and out.destination is None
    assert out.remarks == REMARK_NO_KICK


def test_blank_destination_not_rewritten_when_nothing_to_write():
    out = transition("kick", "twitch", res("EXISTS", "NO_MATCH"), existing_destination=None)
    assert not out.write_destination


def test_user_remark_is_never_erased():
    out = transition(
        "kick", "twitch", res("NOT_FOUND", "NO_MATCH", "NOT_FOUND"), existing_remarks="call back monday"
    )
    assert not out.write_remarks
    out2 = transition("kick", "twitch", res("EXISTS", "MATCH"), existing_remarks="call back monday")
    assert not out2.write_remarks


def test_app_remark_from_previous_run_is_replaced_or_cleared():
    out = transition("kick", "twitch", res("EXISTS", "MATCH"), existing_remarks="no kick id")
    assert out.write_remarks and out.remarks is None
    out2 = transition(
        "twitch", "kick", res("NOT_FOUND", "NO_MATCH", "NOT_FOUND"), existing_remarks="no kick id"
    )
    assert out2.write_remarks and out2.remarks == REMARK_NO_BOTH


# ------------------------------------------------------------------ any other pair
@pytest.mark.parametrize(
    ("resolution", "remark"),
    [
        (res("EXISTS", "MATCH"), None),
        (res("EXISTS", "REVIEW", review="cand"), "no youtube id found"),
        (res("EXISTS", "NO_MATCH"), "no youtube id found"),
        (res("NOT_FOUND", "MATCH", "VERIFIED"), "no twitch channel found"),
        (res("NOT_FOUND", "NO_MATCH", "NOT_FOUND"), REMARK_NO_BOTH),
    ],
)
def test_platform_names_follow_the_chosen_pair(resolution, remark):
    out = transition("twitch", "youtube", resolution)
    assert out.remarks == remark
    assert out.case.startswith("TWITCH_")


def test_own_remarks_of_other_platforms_are_recognised():
    out = transition("youtube", "kick", res("EXISTS", "MATCH"), existing_remarks="no kick id")
    assert out.write_remarks and out.remarks is None


def test_preserved_row_keeps_its_remark():
    out = transition(
        "twitch", "kick", res("EXISTS", "NO_MATCH"), existing_destination="x", existing_remarks="mine"
    )
    assert out.status == RowStatus.PRESERVED and not out.write_remarks and out.link == "preserved"
