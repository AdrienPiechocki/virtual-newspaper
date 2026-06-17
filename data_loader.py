"""
data_loader.py
Charge les CSV produits par les différents scripts (RSS, Steam, LinkedIn, météo)
et les normalise en structures Python prêtes à être injectées dans le template HTML.
"""

import csv
from pathlib import Path
from datetime import datetime


def _read_csv(path: Path) -> list[dict]:
    """Lit un CSV et retourne une liste de dicts. Retourne [] si le fichier est absent."""
    if not path.exists():
        print(f"[warn] fichier introuvable : {path}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_rss_articles(path: Path) -> list[dict]:
    """
    rss_reader.py exporte un CSV avec les colonnes : title, url, body
    (pas de date ni de source : pas de tri possible, on garde l'ordre du flux)
    """
    rows = _read_csv(path)
    return rows


def load_steam_games(path: Path) -> dict[str, list[dict]]:
    rows = _read_csv(path)
    trending = [r for r in rows if r.get("section") == "trending"]
    upcoming = [r for r in rows if r.get("section") == "upcoming"]
    return {"trending": trending, "upcoming": upcoming}


def load_linkedin_jobs(path: Path) -> list[dict]:
    rows = _read_csv(path)
    rows.sort(key=lambda r: r.get("posted_date", ""), reverse=True)
    return rows


def load_weather(path: Path) -> list[dict]:
    """
    weather_forecast.py exporte un CSV avec une ligne par région/jour :
    date, region, t_max, t_min, rain_mm, wind_kmh, sky_label,
    hottest_city, hottest_temp, coldest_city, coldest_temp,
    national_avg_max, national_avg_min

    On ne garde que le jour le plus proche (premier en date) pour le journal,
    et on trie les régions par t_max décroissant pour un affichage plus lisible.
    """
    rows = _read_csv(path)
    if not rows:
        return []

    first_date = rows[0]["date"]
    today_rows = [r for r in rows if r["date"] == first_date]
    today_rows.sort(key=lambda r: float(r.get("t_max", 0)), reverse=True)
    return today_rows


def load_all(data_dir: Path) -> dict:
    """Point d'entrée unique : charge toutes les sources depuis data_dir."""
    return {
        "rss_articles": load_rss_articles(data_dir / "rss_articles.csv"),
        "steam_games": load_steam_games(data_dir / "steam_games.csv"),
        "linkedin_jobs": load_linkedin_jobs(data_dir / "linkedin_jobs.csv"),
        "weather": load_weather(data_dir / "weather_bulletin.csv"),
        "generated_at": datetime.now(),
    }