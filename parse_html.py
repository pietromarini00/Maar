"""
Parse Google Images search result HTML into a list of image records.

Usage:
    from parse_html import parse_google_images_html
    records = parse_google_images_html(html_string)

Each record contains:
    img_url        — full-resolution image URL
    thumbnail_url  — encrypted-tbn Google thumbnail URL
    source_url     — web page the image comes from
    title          — human-readable page title (from "2003"[3] in Google's embedded JSON)
    source_domain  — hostname of the source page
"""

import re
import time
from bs4 import BeautifulSoup

# Google domains whose images we ignore
_SKIP_DOMAINS = (
    "gstatic.com", "google.com", "googleapis.com",
    "googleusercontent.com", "youtube.com", "ytimg.com",
)

# Matches a [thumbnail_url, w, h], [original_url, w, h] pair embedded in Google's page JS.
# Thumbnail is always from encrypted-tbn*.gstatic.com; original is the real image.
# No file-extension requirement — CDN proxy URLs and IIIF endpoints have none.
_PAIR_RE = re.compile(
    r'\["(https://encrypted-tbn[^"]+)",\s*\d+,\s*\d+\]\s*,\s*'
    r'\["(https://(?!(?:encrypted-tbn|gstatic|google|googleuser))[^"]+)",\s*\d+,\s*\d+\]',
    re.IGNORECASE,
)

_UNICODE_ESC_RE = re.compile(r'\\u([0-9a-fA-F]{4})')


def _decode_escapes(html: str) -> str:
    """Decode \\xNN and \\uNNNN escapes present in Google AJAX responses."""
    try:
        html = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), html)
        html = _UNICODE_ESC_RE.sub(lambda m: chr(int(m.group(1), 16)), html)
    except Exception:
        pass
    return html


def _normalize_url(url: str) -> str:
    """Decode any remaining \\uNNNN / \\xNN escapes inside an extracted URL."""
    url = _UNICODE_ESC_RE.sub(lambda m: chr(int(m.group(1), 16)), url)
    url = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1), 16)), url)
    return url


def _extract_meta(ctx: str) -> tuple[str, str, str]:
    """
    Pull (source_url, title, domain) from the ~600-char JSON context
    that follows each image pair in Google's embedded data structure.

    Google embeds per-image metadata in a "2003" array:
        "2003":[null, id, source_page_url, page_title, ...]
    and a "2000" array:
        "2000":[null, domain, file_size]
    """
    source_url, title, domain = "", "", ""

    m = re.search(
        r'"2003":\[null,"[^"]*","(https://[^"]+)","([^"]*)"',
        ctx,
    )
    if m:
        source_url = m.group(1)
        title = m.group(2)

    m2 = re.search(r'"2000":\[null,"([^"]+)"', ctx)
    if m2:
        domain = m2.group(1)

    return source_url, title, domain


def parse_google_images_html(html: str) -> list[dict]:
    """
    Parse a Google Images HTML page (full or AJAX continuation) and return
    a deduplicated list of image records sorted by appearance order.
    """
    decoded = _decode_escapes(html)
    seen_urls: set[str] = set()
    results: list[dict] = []

    for text in dict.fromkeys([html, decoded]):   # skip second pass if identical
        for m in _PAIR_RE.finditer(text):
            thumb_url = m.group(1)
            orig_url  = m.group(2)

            orig_url = _normalize_url(orig_url)

            if orig_url in seen_urls:
                continue
            if any(d in orig_url for d in _SKIP_DOMAINS):
                continue
            seen_urls.add(orig_url)

            # Grab ~600 chars of context after the match to find metadata keys
            ctx = text[m.end(): m.end() + 700]
            source_url, title, domain = _extract_meta(ctx)

            if not domain:
                domain = re.sub(r"https?://(?:www\.)?([^/]+).*", r"\1", orig_url)
            if not title:
                slug = orig_url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                title = slug.replace("-", " ").replace("_", " ")

            results.append({
                "img_url":       orig_url,
                "thumbnail_url": thumb_url,
                "source_url":    source_url,
                "title":         title[:200],
                "source_domain": domain,
            })

    return results


def lens_exact_match_count(img_path, session=None) -> int:
    """
    Upload a local image to Google Lens and return the exact-match result count.

    Uses the "Find image source" tab (udm=48).  The result count is parsed from
    the server-rendered HTML using the selector 'a.ngTNl[data-hveid]', which
    matches each result card link — more reliable than the '#result-stats' text,
    which is a JS-rendered placeholder and often shows "0 results" even when
    real results exist.

    Returns:
        int >= 0  — number of exact-match result cards
        -1        — CAPTCHA / blocked
        -2        — upload or fetch error
    """
    from pathlib import Path
    from curl_cffi import requests as curl_requests, CurlMime

    img_path = Path(img_path)
    if not img_path.exists():
        return -2

    if session is None:
        session = curl_requests.Session(impersonate="firefox135")

    # Upload image to Google Lens
    try:
        mp = CurlMime()
        mp.addpart(
            name="encoded_image",
            data=img_path.read_bytes(),
            filename=img_path.name,
            content_type="image/jpeg",
        )
        upload_resp = session.post(
            "https://lens.google.com/upload",
            params={"hl": "en", "re": "df", "st": str(int(time.time() * 1000))},
            multipart=mp,
            allow_redirects=True,
            timeout=30,
        )
    except Exception:
        return -2

    landing_url = str(upload_resp.url)
    if "vsrid=" not in landing_url and "gsessionid=" not in landing_url:
        return -2

    # Extract the exact-matches tab URL from the visual-matches page.
    # The tab href includes lns_surface=26 and the full vsrid/session params —
    # simply swapping udm= in the landing URL misses lns_surface=26 and returns 0.
    decoded = _decode_escapes(upload_resp.text)
    m = re.search(r'href=["\']([^"\'> ]*udm=48[^"\'> ]*)["\']', decoded)
    if m:
        href = m.group(1).replace("&amp;", "&")
        exact_url = "https://www.google.com" + href if href.startswith("/") else href
    else:
        # Fallback: swap udm in landing URL + add lns_surface=26
        exact_url = re.sub(r"udm=\d+", "udm=48", landing_url)
        if "lns_surface=26" not in exact_url:
            exact_url += "&lns_surface=26"

    # Wait for the Lens session to finish processing before fetching exact matches.
    # Without this pause the server may not yet have results ready.
    time.sleep(3)

    try:
        exact_resp = session.get(exact_url, timeout=20)
    except Exception:
        return -2

    resp_text = exact_resp.text
    if "CAPTCHA" in resp_text or "sorry" in str(exact_resp.url).lower():
        return -1

    # Count result cards via the server-rendered anchor elements.
    # '#result-stats' text ("About N results") is a JS placeholder — unreliable.
    soup = BeautifulSoup(_decode_escapes(resp_text), "html.parser")
    cards = soup.select("a.ngTNl[data-hveid]")
    return len(cards)


def vision_web_count(img_path, credentials_json: str, client=None) -> int:
    """
    Use the Google Cloud Vision API Web Detection to count how many web pages
    contain this image (pages_with_matching_images).

    Args:
        img_path:         Path to a local image file.
        credentials_json: Path to the Google Cloud service-account JSON key.
        client:           Optional pre-built ImageAnnotatorClient to reuse.

    Returns:
        int >= 0  — number of pages with matching images
        -2        — file not found or API error
    """
    import os
    from pathlib import Path
    from google.cloud import vision as gv

    img_path = Path(img_path)
    if not img_path.exists():
        return -2

    try:
        if client is None:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_json)
            client = gv.ImageAnnotatorClient()

        image = gv.Image(content=img_path.read_bytes())
        resp = client.web_detection(image=image, max_results=500)

        if resp.error.message:
            return -2

        return len(resp.web_detection.pages_with_matching_images)
    except Exception:
        return -2


def scrape_picasso_dora_maar(session=None) -> list[dict]:
    """
    Scrape Picasso's Dora Maar artworks from pablo-ruiz-picasso.net.

    Visits the listing page to collect image URLs and detail-page links,
    then visits each detail page for clean h1 (title) and h2 (year).

    Returns a list of dicts with:
        author, title, year, img_url, thumbnail_url, detail_url, source_domain
    """
    import time
    import random
    from curl_cffi import requests as curl_requests

    BASE = "https://www.pablo-ruiz-picasso.net/"
    if session is None:
        session = curl_requests.Session(impersonate="firefox135")

    # --- Step 1: listing page —  collect thumbnail src + detail href ---
    resp = session.get(BASE + "theme-doramaar.php", timeout=20)
    soup = BeautifulSoup(resp.text, "html.parser")

    stubs = []
    for img in soup.find_all("img", class_="imgGallery"):
        src = img.get("src", "")
        if not src:
            continue
        a_tag = img.parent
        detail_href = a_tag.get("href", "") if a_tag and a_tag.name == "a" else ""
        stubs.append({
            "thumb_src":   src,
            "detail_href": detail_href,
        })

    # --- Step 2: visit each detail page for clean title + year ---
    records = []
    for i, stub in enumerate(stubs):
        src        = stub["thumb_src"]
        full_src   = src.replace("/small/", "/")
        img_url    = BASE + full_src
        thumb_url  = BASE + src
        detail_url = BASE + stub["detail_href"] if stub["detail_href"] else ""

        title, year = "", ""
        if detail_url:
            try:
                d_resp = session.get(detail_url, timeout=15)
                d_soup = BeautifulSoup(d_resp.text, "html.parser")
                h1 = d_soup.find("h1")
                h2 = d_soup.find("h2")
                title = h1.get_text(strip=True) if h1 else ""
                year  = h2.get_text(strip=True) if h2 else ""
                # Discard year if it looks like a section header rather than a date
                if not re.match(r"^\d{4}$", year):
                    year = re.search(r"\b(1\d{3})\b", year)
                    year = year.group(1) if year else ""
            except Exception:
                pass
            time.sleep(random.uniform(0.5, 1.2))

        records.append({
            "author":        "Pablo Picasso",
            "title":         title[:200],
            "year":          year,
            "img_url":       img_url,
            "thumbnail_url": thumb_url,
            "detail_url":    detail_url,
            "source_domain": "pablo-ruiz-picasso.net",
        })

        if (i + 1) % 10 == 0:
            print(f"  scraped {i+1}/{len(stubs)} detail pages…")

    return records


if __name__ == "__main__":
    import sys
    import json
    path = sys.argv[1] if len(sys.argv) > 1 else "google_debug.html"
    html = open(path, encoding="utf-8").read()
    records = parse_google_images_html(html)
    print(f"Parsed {len(records)} images from {path}")
    for r in records[:10]:
        print(f"  [{r['source_domain']}] {r['title'][:60]}")
        print(f"    img: {r['img_url'][:80]}")
        print(f"    src: {r['source_url'][:80]}")