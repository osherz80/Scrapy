"""Stable chain identities, independent of unverified provider mappings."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Chain:
    id: str
    display_name: str


CHAINS: tuple[Chain, ...] = (
    Chain("shufersal", "Shufersal"),
    Chain("carrefour", "Carrefour"),
    Chain("rami-levy", "Rami Levy"),
    Chain("yochananof", "Yochananof"),
    Chain("osher-ad", "Osher Ad"),
    Chain("victory", "Victory"),
    Chain("mahsanei-hashuk", "Mahsanei HaShuk"),
    Chain("hatzi-hinam", "Hatzi Hinam"),
    Chain("tiv-taam", "Tiv Taam"),
    Chain("keshet-teamim", "Keshet Teamim"),
)
