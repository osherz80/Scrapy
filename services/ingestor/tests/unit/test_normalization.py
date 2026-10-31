import json
from pathlib import Path

import pytest

from ingestor.normalization import normalize_name, tokenize

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[4] / "contracts/fixtures/normalization.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", FIXTURES["cases"])
def test_normalization_matches_pinned_backend_javascript(case):
    assert normalize_name(case["input"]) == case["normalized"]
    assert list(tokenize(case["input"])) == case["tokens"]
