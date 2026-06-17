#!/usr/bin/env python3
"""
generate_newspaper.py

Assemble les CSV produits par les autres scripts du projet virtual-newspaper
(rss_reader.py, steam_trending.py, linkedin_jobs_scraper.py, weather_forecast.py)
et génère un PDF unique, mis en page façon journal papier.

Usage:
    python generate_newspaper.py [--data-dir DATA_DIR] [--output OUTPUT_PDF]
"""

import argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from data_loader import load_all

BASE_DIR = Path(__file__).parent
TEMPLATE_DIR = BASE_DIR / "templates"

MOIS_FR = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre"
]


def format_date_fr(dt: datetime) -> str:
    return f"{dt.day} {MOIS_FR[dt.month]} {dt.year}"


def truncate_words(text: str, max_words: int = 70) -> str:
    """Tronque le body complet d'un article scrapé à un extrait lisible style journal."""
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(".,;:") + "…"


def domain_only(url: str) -> str:
    """Affiche juste le domaine (ex: lemonde.fr) au lieu de l'URL complète."""
    if not url:
        return ""
    netloc = urlparse(url).netloc
    return netloc.removeprefix("www.")


def first_tags(tags_str: str, max_tags: int = 4) -> str:
    """
    Les tags Steam mélangent genres et fonctionnalités d'accessibilité
    (ex: 'Aventure, Indépendant, Option souris uniquement, ...') et peuvent
    dépasser 20 entrées pour un même jeu. On n'en garde que les premiers
    pour rester lisible dans la mise en page journal.
    """
    if not tags_str:
        return ""
    parts = [t.strip() for t in tags_str.split(",") if t.strip()]
    return ", ".join(parts[:max_tags])


def build_html(data: dict, masthead: str) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    env.filters["truncate_words"] = truncate_words
    env.filters["domain_only"] = domain_only
    env.filters["first_tags"] = first_tags
    template = env.get_template("newspaper.html.j2")
    css_content = (TEMPLATE_DIR / "newspaper.css").read_text(encoding="utf-8")

    return template.render(
        masthead=masthead,
        date_str=format_date_fr(data["generated_at"]),
        generated_at=data["generated_at"].strftime("%d/%m/%Y à %H:%M"),
        rss_articles=data["rss_articles"],
        steam_games=data["steam_games"],
        linkedin_jobs=data["linkedin_jobs"],
        weather=data["weather"],
        css=css_content,
    )


def generate_pdf(data_dir: Path, output_path: Path, masthead: str = "Le Quotidien d'Adrien"):
    data = load_all(data_dir)
    html_content = build_html(data, masthead)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_content, base_url=str(TEMPLATE_DIR)).write_pdf(str(output_path))

    print(f"[ok] PDF généré : {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Génère le journal PDF à partir des CSV des autres scripts.")
    parser.add_argument("--data-dir", type=Path, default=BASE_DIR / "data",
                         help="Dossier contenant les CSV (rss_articles.csv, steam_games.csv, linkedin_jobs.csv, weather_bulletin.csv)")
    parser.add_argument("--output", type=Path, default=BASE_DIR / "output" / "journal.pdf",
                         help="Chemin du PDF de sortie")
    parser.add_argument("--masthead", type=str, default="Le Quotidien d'Adrien",
                         help="Titre du journal (nom du masthead)")
    args = parser.parse_args()

    generate_pdf(args.data_dir, args.output, args.masthead)


if __name__ == "__main__":
    main()