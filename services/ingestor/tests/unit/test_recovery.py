import pytest

from ingestor.runs.recovery import RecoveryError, final_status


@pytest.mark.parametrize(
    "states,expected",
    [
        (("SUCCEEDED",), "SUCCEEDED"),
        (("SUCCEEDED", "SUCCEEDED"), "SUCCEEDED"),
        (("FAILED",), "FAILED"),
        (("FAILED", "FAILED"), "FAILED"),
        (("SUCCEEDED", "FAILED"), "PARTIAL_FAILED"),
    ],
)
def test_final_outcome_reflects_committed_chain_results(states, expected):
    assert final_status(states) == expected


@pytest.mark.parametrize("states", [(), ("PENDING",), ("RUNNING",), ("unknown",)])
def test_unfinished_or_unknown_outcomes_cannot_be_finalized(states):
    with pytest.raises(RecoveryError, match="UNFINISHED_CHAINS"):
        final_status(states)
