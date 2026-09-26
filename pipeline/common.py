"""Shared paths and helpers used by every pipeline step."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
CROSSWALKS = ROOT / "crosswalks"
SQL_DIR = ROOT / "sql"
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SITE_DATA = ROOT / "site" / "data"
DB_PATH = ROOT / "data" / "pakistan_districts.duckdb"

# ISO 3166-2:PK subdivision codes, used as the prefix of every district_id.
PROVINCES = {
    "punjab": {"code": "PB", "name": "Punjab"},
    "sindh": {"code": "SD", "name": "Sindh"},
    "kp": {"code": "KP", "name": "Khyber Pakhtunkhwa"},
    "balochistan": {"code": "BA", "name": "Balochistan"},
    "islamabad": {"code": "IS", "name": "Islamabad Capital Territory"},
}


def sources_pinned() -> date:
    """Date the sources were last pinned. Outputs are stamped with this rather than
    today's date, so rebuilding unchanged sources gives byte-identical files."""
    lock = json.loads((CONFIG / "sources.lock.json").read_text())
    return date.fromisoformat(lock["_generated"][:10])


def load_yaml(name: str) -> dict:
    with open(CONFIG / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def slugify(text: str) -> str:
    """'Dera Ghazi Khan' -> 'dera_ghazi_khan'. Used for stable identifiers."""
    text = ascii_fold(str(text)).lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def district_id(province_code: str, census_name: str) -> str:
    """Stable district identifier, e.g. ('PB', 'ATTOCK') -> 'pb_attock'.

    IDs are derived from the PBS spelling once and then frozen: display names can
    change, IDs never do (see docs/conventions.md).
    """
    return f"{province_code.lower()}_{slugify(census_name)}"


def title_name(census_name: str) -> str:
    """PBS publishes names in capitals; display them in title case."""
    return " ".join(w.capitalize() for w in str(census_name).split())


# Words that carry no identity when matching place names across sources.
_NAME_NOISE = re.compile(
    r"\b(TEHSIL|TALUKA|TALUKAS|TALUKS|SUB TEHSIL|SUB DIVISION|SUBDIVISION|SUB|"
    r"TOWN|CANTONMENT|CANTT|CITY|DISTRICT|AGENCY)\b"
)


def match_key(name: str) -> str:
    """Aggressive normalisation for matching names between sources.

    'D.I.KHAN' -> 'DI KHAN', 'Aranji Sub' -> 'ARANJI', 'BABA_KOT' -> 'BABA KOT'.
    Only used for joining; never shown to users.
    """
    s = ascii_fold(str(name)).upper().replace("_", " ").replace("-", " ")
    s = s.replace(".", " ")
    s = _NAME_NOISE.sub(" ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()
