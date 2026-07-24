import re

import requests
from bs4 import BeautifulSoup

from .constants import BASE_URL, CALENDAR_TYPE, CROP_LIST_PATH

CROP_HREF_RE = re.compile(rf"/calendar/{CALENDAR_TYPE}/(\d+)/?$")
REGION_HREF_RE = re.compile(rf"/calendar/{CALENDAR_TYPE}/(\d+)/(\d+)/?$")


def _menu_links(html: str) -> list[tuple[str, str]]:
    """Extract (href, label) pairs from the site's '.single_big_btn_menu' link grid."""
    soup = BeautifulSoup(html, "lxml")
    links = []
    for anchor in soup.select("div.single_big_btn_menu a[href]"):
        label_tag = anchor.find("p")
        label = label_tag.get_text(strip=True) if label_tag else anchor.get_text(strip=True)
        links.append((anchor["href"], label))
    return links


def fetch_crops(session: requests.Session) -> list[dict]:
    resp = session.get(f"{BASE_URL}{CROP_LIST_PATH}", timeout=20)
    resp.raise_for_status()
    crops = []
    for href, name in _menu_links(resp.text):
        match = CROP_HREF_RE.search(href)
        if match:
            crops.append({"crop_id": match.group(1), "crop_name": name})
    return crops


def fetch_regions(session: requests.Session, crop_id: str) -> list[dict]:
    resp = session.get(f"{BASE_URL}/en/calendar/{CALENDAR_TYPE}/{crop_id}", timeout=20)
    resp.raise_for_status()
    regions = []
    for href, name in _menu_links(resp.text):
        match = REGION_HREF_RE.search(href)
        if match:
            regions.append({"crop_id": match.group(1), "region_id": match.group(2), "region_name": name})
    return regions
