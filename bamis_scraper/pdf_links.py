import re

import requests
from bs4 import BeautifulSoup

from .constants import BASE_URL, CALENDAR_TYPE

# Inside each language-toggle button's onclick handler:
#   document.getElementById('preview').src='https://.../calendars/.../123.pdf';...
PDF_SRC_RE = re.compile(r"""src=['"]([^'"]+\.pdf)['"]""")


def fetch_pdf_links(session: requests.Session, crop_id: str, region_id: str) -> list[str]:
    """Both language versions of the calendar are embedded in one page load, via the
    #lan1/#lan2 language-toggle buttons. Which button targets Bangla vs English flips
    depending on the *session's current language cookie state* (server renders
    "current language" vs "switch to other language" positionally) - so button id
    is NOT a reliable language signal. Callers must determine language from the PDF
    content itself (see pdf_store.detect_language)."""
    url = f"{BASE_URL}/calendar/{CALENDAR_TYPE}/{crop_id}/{region_id}/"
    resp = session.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    urls = []
    for button_id in ("lan1", "lan2"):
        button = soup.find(id=button_id)
        if not button:
            continue
        match = PDF_SRC_RE.search(button.get("onclick", ""))
        if match:
            urls.append(match.group(1))
    return urls
