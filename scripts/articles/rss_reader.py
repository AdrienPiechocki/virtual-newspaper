#!/usr/bin/env python3
"""
Reads an RSS feed and extracts the text content of each article via article_scraper.
Usage: python rss_reader.py <rss_url> [--limit N] [--csv output.csv]
"""

import sys
import argparse
import csv
import xml.etree.ElementTree as ET
import urllib.request
from scripts.articles.article_scraper import fetch_article

import re
from bs4 import BeautifulSoup

def is_code_heavy_article(html: str) -> bool:
    if not html:
        return False

    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text("\n")
    if len(text) < 300:
        return False  # too short = not reliable

    code_blocks = soup.find_all(["pre", "code"])

    code_text = "\n".join(cb.get_text("\n") for cb in code_blocks)

    code_ratio = len(code_text) / max(len(text), 1)

    # only if REALLY dominated by code
    return (
        len(code_blocks) >= 1
    )

import urllib.request

def fetch_html(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8", errors="replace")

def is_too_sparse_text(text: str) -> bool:
    if not text:
        return True

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    
    if len(lines) < 15:
        return True

    # check number of words per line
    too_short_lines = sum(len(line.split()) < 5 for line in lines)

    # if too many lines are weak, we reject
    if too_short_lines > len(lines)/2:
        return True

    return False

def fetch_rss(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_feed(xml_text: str) -> list[dict]:
    """Parse RSS 2.0 or Atom, returns a list of {title, url}."""
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = []

    # RSS 2.0
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el  = item.find("link")
        if link_el is not None and link_el.text:
            items.append({
                "title": title_el.text.strip() if title_el is not None else "(no title)",
                "url":   link_el.text.strip(),
            })

    # Atom
    if not items:
        for entry in root.findall(".//atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            link_el  = entry.find("atom:link", ns)
            url = link_el.get("href") if link_el is not None else None
            if url:
                items.append({
                    "title": title_el.text.strip() if title_el is not None else "(no title)",
                    "url":   url.strip(),
                })

    return items


def main():
    parser = argparse.ArgumentParser(description="Reads an RSS feed and displays article content.")
    parser.add_argument("rss_url", help="RSS feed URL")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of articles to process")
    parser.add_argument("--scrape", action="store_true", help="Scrape the articles")
    parser.add_argument("--csv", metavar="FILE", help="Export results to a CSV file")
    args = parser.parse_args()

    print(f"Fetching feed: {args.rss_url}", file=sys.stderr)
    xml_text = fetch_rss(args.rss_url)
    items = parse_feed(xml_text)

    if not items:
        print("No articles found in the feed.", file=sys.stderr)
        sys.exit(1)

    if args.limit:
        items = items[: args.limit]

    print(f"{len(items)} article(s) found.\n", file=sys.stderr)

    csv_writer = None
    csv_file = None
    if args.csv:
        csv_file = open(args.csv, "w", newline="", encoding="utf-8")
        csv_writer = csv.writer(csv_file, quoting=csv.QUOTE_ALL)
        csv_writer.writerow(["title", "url", "body"])

    try:
        for i, item in enumerate(items, 1):
            print(f"{'='*60}")
            print(f"[{i}/{len(items)}] {item['title']}")
            print(f"URL: {item['url']}")
            print(f"{'='*60}")

            content = ""
            if args.scrape:
                try:
                    html = fetch_html(item["url"])
                    
                    if is_code_heavy_article(html):
                        print("(article skipped: code-oriented content)", file=sys.stderr)
                        continue

                    content = fetch_article(item["url"]) or ""
                    if is_too_sparse_text(content):
                        print("(article skipped: content too short or sparse)", file=sys.stderr)
                        continue
                    if "Participer au live" in content:
                        print("(article skipped: live event)", file=sys.stderr)
                        continue
                    if content:
                        print(content)
                    else:
                        print("(content not extracted)")
                except Exception as e:
                    print(f"Error during scraping: {e}", file=sys.stderr)
                print()

            if csv_writer:
                csv_writer.writerow([item["title"], item["url"], content])

    finally:
        if csv_file:
            csv_file.close()
            print(f"\nCSV exported: {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()