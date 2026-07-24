import requests

from .constants import AGRO_CLIMATIC_TYPES, BASE_URL, EDAPHIC_TYPES


def fetch_agro_climatic(session: requests.Session, upazila_code: str) -> list[dict]:
    """One row per (type, param) e.g. {'type': 'pktp', 'param': 'P5', 'area': ..., 'percent': ..., 'len': ...}."""
    rows = []
    for type_key in AGRO_CLIMATIC_TYPES:
        resp = session.get(f"{BASE_URL}/agcli/{type_key}/{upazila_code}", timeout=15)
        resp.raise_for_status()
        for record in resp.json():
            rows.append({"upazila_code": upazila_code, "type": type_key, **record})
    return rows


def fetch_edaphic(session: requests.Session, upazila_code: str) -> list[dict]:
    """One row per (type, category) e.g. {'type': 'landtype', 'category': 'High Land', 'area': ...}."""
    rows = []
    for type_key in EDAPHIC_TYPES:
        resp = session.get(f"{BASE_URL}/edaphic/{type_key}/{upazila_code}", timeout=15)
        resp.raise_for_status()
        for record in resp.json():
            category = record.pop(type_key)
            rows.append({"upazila_code": upazila_code, "type": type_key, "category": category, **record})
    return rows


def fetch_map_units(session: requests.Session, upazila_code: str) -> list[dict]:
    """'Others' tab: land-cover map units (agri land sub-units, settlement, river, waterbody, ...)."""
    resp = session.get(f"{BASE_URL}/mu/area/{upazila_code}", timeout=15)
    resp.raise_for_status()
    return [{"upazila_code": upazila_code, **record} for record in resp.json()]
