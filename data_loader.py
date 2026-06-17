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
    """
    steam_trending.py exporte désormais un CSV avec 4 valeurs possibles pour
    "section" : released, upcoming, demos, sales.

    - "released"  = jeux déjà sortis et tendance (-> "En vogue sur Steam")
    - "upcoming"  = jeux pas encore sortis ; release vaut soit une date
      réelle (YYYY-MM-DD) soit la chaîne littérale "Upcoming".
    - "demos"     = démos jouables ; score/price toujours vides (gratuit).
    - "sales"     = jeux actuellement en promotion. Pour l'instant ce sont
      des DOUBLONS des jeux "released" (même appid, même prix, pas encore
      de % de réduction ni de prix barré dans le CSV). On les utilise donc
      seulement pour marquer ces jeux comme "en promo" dans la liste
      released, plutôt que de les afficher une seconde fois.
      Quand le script exportera un vrai discount_percent, on pourra
      ré-afficher "sales" comme bloc à part avec le pourcentage.

    Les sections sont déjà triées par score décroissant par le script ;
    on ne retrie pas pour respecter ce classement.
    """
    rows = _read_csv(path)
    released = [r for r in rows if r.get("section") == "released"]
    upcoming = [r for r in rows if r.get("section") == "upcoming"]
    demos = [r for r in rows if r.get("section") == "demos"]
    sales = [r for r in rows if r.get("section") == "sales"]

    sale_appids = {r["appid"] for r in sales if r.get("appid")}
    for r in released:
        r["on_sale"] = r.get("appid") in sale_appids

    return {"trending": released, "upcoming": upcoming, "demos": demos, "sales": sales}


def load_linkedin_jobs(path: Path) -> list[dict]:
    """
    linkedin_scraper.py exporte un CSV avec les colonnes :
    score, title, company, location, work_type, date_posted,
    search_keyword, skills_found, job_id, url, description

    Déjà trié par score décroissant à l'export, mais on retrie ici
    par sécurité (le score reflète le matching avec les compétences
    recherchées dans la config).
    """
    rows = _read_csv(path)
    rows.sort(key=lambda r: float(r.get("score", 0) or 0), reverse=True)
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