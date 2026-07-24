import pandas as pd
import requests

from .constants import ADMIN_ENDPOINT


def get_divisions(session: requests.Session) -> list[dict]:
    resp = session.post(ADMIN_ENDPOINT, data={"request": "forDiv", "column": "division_n"})
    resp.raise_for_status()
    return resp.json()


def get_districts(session: requests.Session, division_code: str) -> list[dict]:
    resp = session.post(ADMIN_ENDPOINT, data={"request": "forDist", "division_code": division_code})
    resp.raise_for_status()
    return resp.json()


def get_upazilas(session: requests.Session, division_code: str, district_code: str) -> list[dict]:
    resp = session.post(
        ADMIN_ENDPOINT,
        data={"request": "forThana", "division_code": division_code, "district_code": district_code},
    )
    resp.raise_for_status()
    return resp.json()


def build_admin_table(session: requests.Session) -> pd.DataFrame:
    """Walk division -> district -> upazila and return one row per upazila."""
    rows = []
    for division in get_divisions(session):
        div_code, div_name = division["code"], division["name_en"]
        for district in get_districts(session, div_code):
            dist_code, dist_name = district["code"], district["name_en"]
            for upazila in get_upazilas(session, div_code, dist_code):
                rows.append(
                    {
                        "division_code": div_code,
                        "division_name": div_name,
                        "district_code": dist_code,
                        "district_name": dist_name,
                        "upazila_code": upazila["code"],
                        "upazila_name": upazila["name_en"],
                        "upazila_name_bn": upazila["name_bn"],
                    }
                )
    return pd.DataFrame(rows)
