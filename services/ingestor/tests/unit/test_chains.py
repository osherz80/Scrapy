from dataclasses import FrozenInstanceError

import pytest

from ingestor.chains import CHAINS


def test_registry_matches_exact_spec_chain_ids():
    assert {chain.id for chain in CHAINS} == {
        "shufersal",
        "carrefour",
        "rami-levy",
        "yochananof",
        "osher-ad",
        "victory",
        "mahsanei-hashuk",
        "hatzi-hinam",
        "tiv-taam",
        "keshet-teamim",
    }
    assert len(CHAINS) == 10
    assert all(chain.display_name.strip() for chain in CHAINS)


def test_chain_identity_is_immutable():
    with pytest.raises(FrozenInstanceError):
        CHAINS[0].id = "different"
