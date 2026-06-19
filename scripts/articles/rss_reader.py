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
from urllib.parse import urljoin, urlparse
from scripts.articles.article_scraper import fetch_article

import re
from bs4 import BeautifulSoup

from difflib import SequenceMatcher

def is_too_similar(new_title: str, seen_titles: list[str], threshold: float = 0.6) -> bool:
    """Vérifie si le titre est trop similaire à un titre déjà vu."""
    for seen in seen_titles:
        # Calcule le ratio de similarité (0.0 à 1.0)
        similarity = SequenceMatcher(None, new_title.lower(), seen.lower()).ratio()
        if similarity >= threshold:
            return True
    return False

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

def fetch_rss_playwright(url: str) -> str:
    """Fallback pour les flux protégés par Cloudflare (timeout/403 en urllib).
    Ouvre un vrai navigateur (headless=False) pour passer le challenge JS,
    comme dans steam_trending.py."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        )
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        content = page.content()
        # Le rendu navigateur enveloppe le XML dans du HTML (DOM XML viewer) :
        # on récupère le texte brut du <pre> si présent, sinon tout le contenu.
        try:
            pre = page.query_selector("pre")
            if pre:
                content = pre.inner_text()
        except Exception:
            pass
        browser.close()
        return content


def scrape_homepage(html: str, base_url: str) -> list[dict]:
    """Extrait une liste d'articles {title, url} depuis une page HTML
    (page d'accueil ou page de catégorie WordPress), en se basant sur le
    motif standard <h2>/<h3> contenant un unique <a> (entry-title).
    Sert de remplacement quand le site n'a pas de flux RSS fiable."""
    soup = BeautifulSoup(html, "html.parser")
    domain = urlparse(base_url).netloc

    items = []
    seen_urls = set()

    for heading in soup.find_all(["h1", "h2", "h3"]):
        link = heading.find("a", href=True)
        if not link:
            continue

        title = link.get_text(strip=True)
        if not title or len(title) < 8:
            continue

        href = urljoin(base_url, link["href"])

        # On ne garde que les liens internes au même domaine, qui ressemblent
        # à des articles (pas des liens de catégorie/tag/pagination/auteur)
        if urlparse(href).netloc != domain:
            continue
        if any(seg in href for seg in ["/Categorie/", "/tag/", "/page/", "/auteur/", "#"]):
            continue
        if href in seen_urls:
            continue

        seen_urls.add(href)
        items.append({"title": title, "url": href})

    return items


def fetch_rss(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"(urllib failed: {e} — retrying with Playwright)", file=sys.stderr)
        return fetch_rss_playwright(url)


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
    parser = argparse.ArgumentParser(description="Reads multiple RSS feeds and displays article content.")
    # On change rss_url en rss_urls avec nargs='+'
    parser.add_argument("rss_urls", nargs='+', help="List of RSS feed URLs")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of articles per feed")
    parser.add_argument("--scrape", action="store_true", help="DO NOT scrape the articles")
    parser.add_argument("--csv", default="data/rss_articles.csv", metavar="FILE", help="Export results to a CSV file")
    args = parser.parse_args()

    seen_titles = []

    # Initialisation du fichier CSV
    csv_file = None
    csv_writer = None
    if args.csv:
        csv_file = open(args.csv, "w", newline="", encoding="utf-8")
        csv_writer = csv.writer(csv_file, quoting=csv.QUOTE_ALL)
        csv_writer.writerow(["feed_url", "title", "url", "body"]) # Ajout de la colonne feed_url pour s'y retrouver

    try:
        # Boucle sur chaque URL fournie
        for rss_url in args.rss_urls:
            print(f"\n{'#'*20}\nFetching feed: {rss_url}\n{'#'*20}", file=sys.stderr)
            
            try:
                raw = fetch_rss(rss_url)
                try:
                    items = parse_feed(raw)
                except ET.ParseError:
                    print(f"(not a valid RSS/Atom feed — falling back to HTML scraping)", file=sys.stderr)
                    items = scrape_homepage(raw, rss_url)
            except Exception as e:
                print(f"Failed to fetch feed {rss_url}: {e}", file=sys.stderr)
                continue

            if not items:
                print("No articles found in this feed.", file=sys.stderr)
                continue

            if args.limit:
                items = items[:args.limit]
            
            # Traitement des articles du flux actuel
            for i, item in enumerate(items, 1):
                print(f"{'='*60}")
                print(f"[{i}/{len(items)}] {item['title']}")
                print(f"URL: {item['url']}")
                print(f"{'='*60}")

                if is_too_similar(item['title'], seen_titles):
                    print(f"Skipping duplicate: {item['title']}", file=sys.stderr)
                    continue
                
                content = ""
                if not args.scrape:
                    try:
                        html = fetch_html(item["url"])
                        
                        if is_code_heavy_article(html):
                            print("(article skipped: code-oriented content)", file=sys.stderr)
                            continue

                        content = fetch_article(item["url"]) or ""
                        if "Participer au live" in content or "EN DIRECT" in item['title'] or "Plus d’informations à venir" in content:
                            print("(article skipped: live event)", file=sys.stderr)
                            continue
                        if "réservée aux abonnés" in content:
                            print("(article skipped: abonnement requis)", file=sys.stderr)
                            continue
                        if content:
                            print(content)
                            seen_titles.append(item['title'])
                        else:
                            print("(content not extracted)")
                    except Exception as e:
                        print(f"Error during scraping: {e}", file=sys.stderr)
                    print()

                if csv_writer:
                    csv_writer.writerow([rss_url, item["title"], item["url"], content])

    finally:
        if csv_file:
            csv_file.close()
            print(f"\nCSV exported: {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()