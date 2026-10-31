import pytest

from ingestor.runs.admission import AdmissionError, validate_request


@pytest.mark.parametrize(
    "chains,origin,code",
    [
        ((), "MANUAL", "INVALID_REQUESTED_CHAINS"),
        (("victory", "victory"), "MANUAL", "INVALID_REQUESTED_CHAINS"),
        (("unsafe text",), "MANUAL", "INVALID_REQUESTED_CHAINS"),
        ((None,), "MANUAL", "INVALID_REQUESTED_CHAINS"),
        ("victory", "MANUAL", "INVALID_REQUESTED_CHAINS"),
        (("carrefour",), "MANUAL", "SOURCE_DEFERRED"),
        (("shufersal",), "MANUAL", "SOURCE_DEFERRED"),
        (("victory",), "unsafe text", "INVALID_RUN_ORIGIN"),
    ],
)
def test_request_validation_returns_only_static_diagnostics(chains, origin, code):
    with pytest.raises(AdmissionError, match=f"^{code}$"):
        validate_request(chains, origin)


def test_request_order_is_canonical():
    assert validate_request(("victory", "osher-ad"), "SCHEDULED") == ("osher-ad", "victory")
