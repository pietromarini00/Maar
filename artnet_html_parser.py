"""
Parse Artnet artist pages into a DataFrame of artworks.

Usage from a notebook:
    from artnet_html_parser import parse_pages
    df = parse_pages(html_pages)

Usage from the command line (reads HTML files saved by save_pages):
    python artnet_html_parser.py --html-dir artnet_html --out artnet_catalog_raw.csv
"""

import re
import json
import argparse
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup


def parse_page(html: str, page_num: int = 0) -> list[dict]:
    """Extract artwork records from a single Artnet artist page."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []

    for div in soup.select("div.result.artwork"):
        img_tag   = div.find("img")
        em_tag    = div.find("em")
        a_tag     = div.find("a", class_="details-link")
        venue_tag = div.find("a", class_="venue-link")

        raw_src = img_tag.get("src", "") if img_tag else ""
        img_url = ("https:" + raw_src) if raw_src.startswith("//") else raw_src

        alt_text  = img_tag.get("alt", "") if img_tag else ""
        alt_parts = [p.strip() for p in alt_text.rsplit(",", 1)]
        title     = em_tag.text.strip() if em_tag else alt_parts[0]
        year      = alt_parts[-1].strip() if len(alt_parts) > 1 else ""

        href       = a_tag.get("href", "") if a_tag else ""
        detail_url = ("https://www.artnet.com" + href) if href.startswith("/") else href

        gallery_name = venue_tag.get_text(strip=True) if venue_tag else ""
        venue_href   = venue_tag.get("href", "") if venue_tag else ""
        gallery_url  = ("https://www.artnet.com" + venue_href) if venue_href.startswith("/") else venue_href

        listing_type = div.get("data-trigger", "")

        # Walk plain-text <p> tags (no <a> child) to extract sale_date and price/status
        sale_date = ""
        price     = ""
        for p in div.find_all("p"):
            if p.find("a"):
                continue
            text = p.get_text(strip=True)
            if text.lower().startswith("sale date:"):
                sale_date = text[len("sale date:"):].strip()
            else:
                price = text  # last non-link <p> wins (Sold / EUR amount / Auction Closed)

        if img_url:
            rows.append({
                "page":         page_num,
                "title":        title,
                "year":         year,
                "listing_type": listing_type,
                "gallery_name": gallery_name,
                "gallery_url":  gallery_url,
                "price":        price,
                "sale_date":    sale_date,
                "img_url":      img_url,
                "detail_url":   detail_url,
            })

    return rows


def parse_pages(html_pages: dict) -> pd.DataFrame:
    """
    Parse a dict of {page_number: html_string} into a deduplicated DataFrame.

    Returns columns: page, title, year, listing_type, gallery_name, gallery_url, price, sale_date, img_url, detail_url
    """
    rows = []
    for page_num, html in html_pages.items():
        if html:
            rows.extend(parse_page(html, page_num))

    df = (
        pd.DataFrame(rows)
        .drop_duplicates(subset="img_url")
        .reset_index(drop=True)
    )
    return df


def save_pages(html_pages: dict, out_dir: str | Path) -> None:
    """Save fetched HTML pages to disk so the parser can run standalone later."""
    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True)
    for page_num, html in html_pages.items():
        if html:
            (out_dir / f"page_{page_num:03d}.html").write_text(html, encoding="utf-8")
    print(f"Saved {sum(1 for h in html_pages.values() if h)} HTML files to {out_dir.resolve()}")


def load_pages(html_dir: str | Path) -> dict:
    """Load previously saved HTML files back into a {page_num: html} dict."""
    html_dir = Path(html_dir)
    html_pages = {}
    for path in sorted(html_dir.glob("page_*.html")):
        m = re.search(r"page_(\d+)\.html", path.name)
        if m:
            html_pages[int(m.group(1))] = path.read_text(encoding="utf-8")
    return html_pages


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parse saved Artnet HTML files into a CSV.")
    parser.add_argument("--html-dir", default="artnet_html", help="Directory with page_NNN.html files")
    parser.add_argument("--out", default="artnet_catalog_raw.csv", help="Output CSV path")
    args = parser.parse_args()

    html_pages = load_pages(args.html_dir)
    print(f"Loaded {len(html_pages)} HTML files from {args.html_dir}")

    df = parse_pages(html_pages)
    print(f"Parsed {len(df)} unique artworks")

    df.to_csv(args.out, index=False)
    print(f"Saved to {args.out}")
    print(df.head(10).to_string())