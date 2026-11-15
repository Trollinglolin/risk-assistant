"""Hang Seng Index constituent universe (names, sectors, official weights)."""

from __future__ import annotations

from functools import lru_cache

import yaml

from hkrisk import PROJECT_ROOT
from hkrisk.data import SNAPSHOT_AS_OF

UNIVERSE_PATH = PROJECT_ROOT / "universe" / "hsi_constituents.yaml"
HSI_SNAPSHOT_PATH = PROJECT_ROOT / "data" / f"snapshot_hsi_{SNAPSHOT_AS_OF}.parquet"
EXTRA_NAMES = {"2800.HK": "Tracker Fund (ETF)"}


@lru_cache(maxsize=1)
def load_universe() -> list[dict]:
    return yaml.safe_load(UNIVERSE_PATH.read_text())["constituents"]


def names() -> dict[str, str]:
    return {**EXTRA_NAMES, **{c["ticker"]: c.get("display", c["name"]) for c in load_universe()}}


def sectors() -> dict[str, str]:
    return {c["ticker"]: c["sector"] for c in load_universe()}
