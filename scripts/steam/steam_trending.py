import requests
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import math
import time
from datetime import datetime, timedelta, timezone
import random
import sqlite3
import html
import argparse
import csv
import json
from pathlib import Path
import scripts.steam.scrape_steam_tags as scrape_steam_tags
import dateparser

STEAM_SEARCH = "https://store.steampowered.com/search/results/"
STEAM_APP_DETAILS = "https://store.steampowered.com/api/appdetails"
STEAM_EVENTS = "https://partner.steamgames.com/doc/marketing/upcoming_events"
STEAM_DEMOS = "https://store.steampowered.com/sale/nextfest?tab=23&flavor=trendingwishlisted"

EVENT_KEYWORDS = {
    "next fest": "Next Fest",
    "spring sale": "Spring Sale",
    "summer sale": "Summer Sale",
    "autumn sale": "Autumn Sale",
    "fall sale": "Autumn Sale",
    "winter sale": "Winter Sale",
}

MONTHS = r"(January|February|March|April|May|June|July|August|September|October|November|December)"

date_pattern = re.compile(
    rf"({MONTHS}\s+\d{{1,2}}(?:,\s*\d{{4}})?)\s*[-–]\s*({MONTHS}\s+\d{{1,2}},\s*\d{{4}})"
)

# ----------------------------
# ARGS
# ----------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="SteamDB Trending Engine — detects recent trending games on Steam.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument("--days", "-d", type=int, default=7, metavar="N",
        help="Number of days back for the search window")

    parser.add_argument("--top", "-t", type=int, default=20, metavar="N",
        help="Number of released games to display")

    parser.add_argument("--top-upcoming", type=int, default=20, metavar="N",
        help="Number of upcoming games to display in their dedicated section")

    parser.add_argument("--min-reviews", type=int, default=0.70, metavar="N",
        help="Minimum percentage of positive reviews required to include a released game")

    parser.add_argument("--filters", nargs="+",
        default=["popularnew", "topsellers", "new"],
        choices=["popularnew", "topsellers", "comingsoon", "upcoming", "mostplayed", "new"],
        metavar="FILTER",
        help="Steam filters to use")

    parser.add_argument("--pages", type=int, default=3, metavar="N",
        help="Number of pages to scrape per filter (50 apps/page)")

    parser.add_argument("--upcoming-window-days", type=int, default=30, metavar="N",
        help="Fenêtre de dates pour SteamDB Most Wished : aujourd'hui + N jours (défaut: 30)")

    parser.add_argument("--rate-min", type=float, default=0.6, metavar="SEC",
        help="Minimum delay between requests (seconds)")

    parser.add_argument("--rate-max", type=float, default=1.8, metavar="SEC",
        help="Maximum delay between requests (seconds)")

    parser.add_argument("--db", default="steam_cache.db", metavar="FILE",
        help="Path to the SQLite cache database")

    parser.add_argument("--no-cache", action="store_true",
        help="Ignore cache and force reloading from the API")

    parser.add_argument("--clear-cache", action="store_true",
        help="Clear cache before running scraping")

    parser.add_argument("--output", "-o", default="data/steam_games.csv", metavar="FILE.csv",
        help="Export results to a CSV file (both sections)")

    parser.add_argument("--quiet", "-q", action="store_true",
        help="Show only the final ranking")

    parser.add_argument("--verbose", "-v", action="store_true",
        help="Show details for each processed app")

    parser.add_argument("--tags-include", nargs="+", metavar="TAG", default=[],
        help="Include only games that have ALL of these tags")

    parser.add_argument("--tags-exclude", nargs="+", metavar="TAG", default=["hentai", "adult-content", "nudity", "sexual-content"], 
        help="Exclude games that have AT LEAST ONE of these tags")

    parser.add_argument("--list-tags", action="store_true",
        help="Display all steam tags")

    parser.add_argument("--upcoming-cooldown-days", type=int, default=21, metavar="N",
        help="Days an upcoming game stays hidden after being shown, to surface fresh titles each week (0 = disable)")

    parser.add_argument("--gem-min-reviews", type=int, default=50, metavar="N",
        help="Minimum reviews required for a game to qualify as 'hidden gems'")

    parser.add_argument("--gem-max-reviews", type=int, default=500, metavar="N",
        help="Maximum reviews allowed for a game to qualify as 'hidden gems' (keeps it niche/under-the-radar)")

    parser.add_argument("--gem-min-positive-ratio", type=float, default=0.90, metavar="RATIO",
        help="Minimum positive review ratio (0-1) required for a game to qualify as 'hidden gems'")

    return parser.parse_args()


# ----------------------------
# CACHE (SQLite)
# ----------------------------

def init_db(db_path, clear=False):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    if clear:
        cursor.execute("DROP TABLE IF EXISTS app_cache")
        cursor.execute("DROP TABLE IF EXISTS upcoming_shown_history")
        cursor.execute("DROP TABLE IF EXISTS review_cache")
        cursor.execute("DROP TABLE IF EXISTS tags_cache")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_cache (
            appid TEXT PRIMARY KEY,
            data TEXT,
            timestamp INTEGER
        )
    """)
    # Historique des jeux "upcoming" déjà affichés, pour ne pas répéter
    # les mêmes têtes de classement chaque semaine.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS upcoming_shown_history (
            appid TEXT PRIMARY KEY,
            shown_at INTEGER
        )
    """)
    # Cache du détail positif/négatif des reviews (non fourni par appdetails)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS review_cache (
            appid TEXT PRIMARY KEY,
            pos INTEGER,
            neg INTEGER,
            timestamp INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tags_cache (
            appid TEXT PRIMARY KEY,
            tags TEXT
        )
    """)
    conn.commit()
    return conn, cursor


def get_recently_shown_upcoming(cursor, cooldown_days):
    """Retourne le set des appids upcoming montrés dans la fenêtre de cooldown."""
    if cooldown_days <= 0:
        return set()
    cutoff_ts = int(time.time()) - cooldown_days * 86400
    cursor.execute(
        "SELECT appid FROM upcoming_shown_history WHERE shown_at >= ?",
        (cutoff_ts,)
    )
    return {row[0] for row in cursor.fetchall()}


def mark_upcoming_shown(conn, cursor, appids):
    """Enregistre les jeux upcoming venant d'être affichés dans cette run."""
    now = int(time.time())
    cursor.executemany(
        "REPLACE INTO upcoming_shown_history VALUES (?, ?)",
        [(appid, now) for appid in appids]
    )
    conn.commit()


def prune_upcoming_history(conn, cursor, max_age_days=180):
    """Nettoie les entrées trop anciennes pour ne pas faire grossir la DB indéfiniment."""
    cutoff_ts = int(time.time()) - max_age_days * 86400
    cursor.execute(
        "DELETE FROM upcoming_shown_history WHERE shown_at < ?",
        (cutoff_ts,)
    )
    conn.commit()


def cache_get(cursor, appid, no_cache=False):
    if no_cache:
        return None
    cursor.execute("SELECT data FROM app_cache WHERE appid=?", (appid,))
    row = cursor.fetchone()
    return eval(row[0]) if row else None


def cache_set(conn, cursor, appid, data):
    cursor.execute(
        "REPLACE INTO app_cache VALUES (?, ?, ?)",
        (appid, str(data), int(time.time()))
    )
    conn.commit()


# ----------------------------
# REQUÊTES
# ----------------------------

def get_sale_games():
    appids = []

    params = {
        "specials": 1,
        "ndl": 1,
        "infinite": 1
    }

    r = safe_get(STEAM_SEARCH, params=params)

    if not r:
        return []

    html_block = r.json().get("results_html", "")
    found = re.findall(r'data-ds-appid="(\d+)"', html_block)

    return found

def get_demos(target_url):
    """
    Récupère tous les appids en scannant toutes les balises <a> de la page.
    """
    # Regex : cherche "/app/" suivi de chiffres
    appid_pattern = re.compile(r"/app/(\d+)")
    
    app_ids = set() 
    results = []
    seen_appids = set()

    try:
        def extract_ids(page_obj):
            # On ne fait pas wait_for_selector, on récupère directement
            # Tous les hrefs de la page
            all_hrefs = page_obj.locator("a").evaluate_all("elements => elements.map(el => el.href)")
            
            for url in all_hrefs:
                if url: # Vérifier si le lien existe
                    match = appid_pattern.search(url)
                    if match:
                        app_ids.add(match.group(1))
            return sorted(list(app_ids))

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(target_url, wait_until="networkidle", timeout=10000)
            ids = extract_ids(page)
            browser.close()
            appids =  ids
        
        for appid in appids:
            if appid in seen_appids:
                continue
            seen_appids.add(appid)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
                "Accept-Language": "fr-FR,fr;q=0.9,fr;q=0.8"
            }
            r = safe_get(STEAM_APP_DETAILS, params={"appids": appid, "l": "fr"}, headers=headers)
            if not r:
                continue
            try:
                data = r.json().get(str(appid), {})
                if not data.get("success"):
                    continue
                demos_list = data.get("data", {}).get("demos", [])
                if not demos_list:
                    continue
                demo_appid = demos_list[0].get("appid")
                if not demo_appid:
                    continue
                throttle(0.6, 1.8)
                results.append({"appid": appid, "demo_appid": demo_appid})
            except Exception:
                continue

    except Exception as e:
        print(f"  ❌ Error fetching appids: {e}")

    return results


def safe_get(url, params=None, retries=3, headers=None):
    for i in range(retries):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=20)
            if r.status_code in [429, 403]:
                time.sleep((2 ** i) + random.uniform(1, 3))
                continue
            if r.status_code != 200:
                return None
            return r
        except Exception:
            time.sleep(2)
    return None


def throttle(rate_min, rate_max):
    time.sleep(random.uniform(rate_min, rate_max))


# ----------------------------
# UTIL
# ----------------------------

def parse_event_date(s, default_year=None):
    s = s.strip()
    try:
        if "," not in s and default_year:
            s = f"{s}, {default_year}"
        return datetime.strptime(s, "%B %d, %Y").replace(tzinfo=timezone.utc)
    except:
        return None

def log(x):
    return math.log(max(x, 1))


def parse_release_date(s):
    if not s:
        return None
    try:
        return dateparser.parse(s)
    except (ValueError, TypeError):
        return None

# ----------------------------
# EVENTS
# ----------------------------

def extract_events(html):
    soup = BeautifulSoup(html, "html.parser")

    events = []

    # On cherche des blocs logiques (titres + contenu proche)
    for element in soup.find_all(["h2", "h3", "strong", "p", "li"]):
        text = element.get_text(" ", strip=True).lower()

        event_name = None
        for key, name in EVENT_KEYWORDS.items():
            if key in text:
                event_name = name
                break

        if not event_name:
            continue

        # On regarde le texte proche (parent container)
        container_text = element.parent.get_text(" ", strip=True)

        match = date_pattern.search(container_text)
        if not match:
            continue

        start_raw, end_raw = match.group(1), match.group(3)

        # année fallback (Steam met souvent l'année dans la fin)
        year_match = re.search(r"\d{4}", end_raw)
        year = int(year_match.group()) if year_match else None

        start = parse_event_date(start_raw, year)
        end = parse_event_date(end_raw)

        if start and end:
            events.append((event_name, start, end))

    return events


def get_active_events(headers):
    """
    Retourne la liste (dédupliquée) de tous les events Steam actifs
    actuellement (sale + Next Fest peuvent se chevaucher). Liste vide
    si aucun event, ou si la page Steam est inaccessible (ne lève jamais).
    """
    r = safe_get(STEAM_EVENTS, headers=headers)
    if not r:
        return []

    events = extract_events(r.text)

    now = datetime.now(timezone.utc)

    active = []
    seen = set()
    for name, start, end in events:
        # `end` est parsé à minuit (00:00) ; on inclut tout le dernier jour
        # de l'event en comparant à la fin de journée plutôt qu'à minuit.
        end_of_day = end.replace(hour=23, minute=59, second=59)
        if start <= now <= end_of_day and name not in seen:
            active.append(name)
            seen.add(name)

    return active

# ----------------------------
# TAGS
# ----------------------------

def get_steam_tags(appid, conn, cursor, no_cache, pw_page=None):
    if not no_cache:
        cursor.execute("SELECT tags FROM tags_cache WHERE appid=?", (appid,))
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])

    url = f"https://store.steampowered.com/app/{appid}/"
    tags = []

    try:
        if pw_page is not None:
            # Réutilise la page partagée — pas de nouveau lancement de navigateur
            pw_page.goto(url, wait_until="domcontentloaded", timeout=5000)
            try:
                pw_page.wait_for_selector("a.app_tag", timeout=2000)
                tags = pw_page.locator("a.app_tag").all_text_contents()
            except Exception:
                tags = ["hentai", "adult-content", "nudity", "sexual-content"]
                cursor.execute("REPLACE INTO tags_cache VALUES (?, ?)", (appid, json.dumps(tags)))
                conn.commit()
                return tags
        else:
            # Fallback : lance un navigateur dédié (lent, éviter en prod)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=5000)
                try:
                    page.wait_for_selector("a.app_tag", timeout=2000)
                    tags = page.locator("a.app_tag").all_text_contents()
                except Exception:
                    tags = ["hentai", "adult-content", "nudity", "sexual-content"]
                    cursor.execute("REPLACE INTO tags_cache VALUES (?, ?)", (appid, json.dumps(tags)))
                    conn.commit()
                    return tags
                browser.close()
    except Exception as e:
        print(f"  ❌ Error scraping tags for {appid}: {e}")

    tags = [t.strip() for t in tags if t.strip()]
    tag_list = list(dict.fromkeys(tags))

    cursor.execute("REPLACE INTO tags_cache VALUES (?, ?)", (appid, json.dumps(tag_list)))
    conn.commit()

    return tag_list


def tags_match(tags, exclude):
    for t in exclude:
        if t.lower() in tags:
            return False
    return True


def tags_display(details):
    names = sorted({
        g.get("description", "") for g in details.get("genres", [])
    } | {
        c.get("description", "") for c in details.get("categories", [])
    })
    return ", ".join(n for n in names if n)


# ----------------------------
# SCRAPER
# ----------------------------

def load_tags(path):
    if not path.exists():
        scrape_steam_tags.main()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def build_tag_map(tag_list):
    return {t["name"].lower(): t["id"] for t in tag_list}

def build_tag_query(tag_map, names):
    return ",".join(
        str(tag_map[n.lower().replace(" ", "-")])
        for n in names
        if n.lower().replace(" ", "-") in tag_map
    )

def get_appids(filters, pages, rate_min, rate_max, quiet, tag_map, tag_names, headers):

    appids = set()

    rankings = {
        "upcoming": {},
        "comingsoon": {},
        "topsellers": {},
        "popularnew": {},
    }

    tag_query = build_tag_query(tag_map, tag_names)
    base_category = "998" # Game

    for f in filters:
        global_rank = 1

        for page in range(pages):

            params = {
                "start": page * 50,
                "count": 50,
                "filter": "" if f == "new" else f,
                "infinite": 1,
                "category1": base_category,
            }

            if f == "new":
                params["sort_by"] = "Released_DESC"
            
            if tag_query:
                params["tags"] = tag_query

            r = safe_get(STEAM_SEARCH, params=params, headers=headers)
            
            if not r:
                continue

            html_block = r.json().get("results_html", "")

            found = re.findall(r'data-ds-appid="(\d+)"', html_block)

            for appid in found:
                appids.add(appid)

                if f in rankings and appid not in rankings[f]:
                    rankings[f][appid] = global_rank

                global_rank += 1

            if not quiet:
                print(f"  [{f}] page {page+1}/{pages} — {len(found)} apps")

            throttle(rate_min, rate_max)

    return list(appids), rankings


def get_details(appid, conn, cursor, rate_min, rate_max, no_cache, headers):
    cached = cache_get(cursor, appid, no_cache)
    if cached:
        return cached
    r = safe_get(STEAM_APP_DETAILS, params={"appids": appid, "l": "fr"}, headers=headers)
    if not r:
        return None
    try:
        data = r.json().get(str(appid), {})
        if not data.get("success"):
            return None
        result = data.get("data")
        cache_set(conn, cursor, appid, result)
        throttle(rate_min, rate_max)
        return result
    except Exception:
        return None


def get_review_breakdown(appid, conn, cursor, no_cache):
    """
    Récupère le résumé des reviews via l'API Steam officielle.
    """
    # 1. Vérification du cache pour éviter de spammer l'API
    if not no_cache:
        cursor.execute(
            "SELECT pos, neg FROM review_cache WHERE appid=?", (appid,)
        )
        row = cursor.fetchone()
        if row:
            return row[0], row[1]

    # 2. Appel API (on demande 0 review, juste le query_summary)
    url = f"https://store.steampowered.com/appreviews/{appid}"
    params = {
        "json": 1, 
        "language": "all", 
        "num_per_page": 0,
        "filter_offtopic_activity": 1 # Filtre le review bombing
    }
    
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        
        if data.get("success") == 1:
            summary = data.get("query_summary", {})
            
            # CORRECTION : Enlever la virgule à la fin
            pos = summary.get("total_positive", 0) 
            neg = summary.get("total_negative", 0)
            
            # Mise en cache
            cursor.execute(
                "REPLACE INTO review_cache VALUES (?, ?, ?, ?)",
                (appid, pos, neg, int(time.time())) # Stocker des entiers directement
            )
            conn.commit()
            return pos, neg
    except Exception as e:
        print(f"  ⚠️ Erreur API reviews pour {appid}: {e}")
        
    return 0, 0


# ----------------------------
# SCORING — jeux sortis
# ----------------------------

def trend_score(pos, neg, release_date):
    total = pos + neg
    days = max((datetime.now() - release_date).days, 1)
    if total < 1:
        post = 0
    else:
        ratio = pos / (total + 1)
        velocity = total / days
        post = (
            0.5 * velocity * 10 +
            0.3 * ratio * 100 +
            0.2 * log(total)
        )
    decay = 1 / math.sqrt(days)
    return log(post * decay + 1) * 12


def confidence(pos, neg):
    total = pos + neg
    if total > 500: return 1.0
    if total > 100: return 0.8
    if total > 20:  return 0.6
    if total > 5:   return 0.4
    return 0.2


def released_score(pos, neg, release_date):
    return trend_score(pos, neg, release_date) * confidence(pos, neg)


# ----------------------------
# HIDDEN GEMS
# ----------------------------

def is_gem(pos, neg, min_reviews, max_reviews, min_ratio):
    """
    Détecte un jeu 'pépite indé' : peu de reviews (donc peu visible /
    sous-médiatisé) mais un ratio positif très élevé.
    """
    total = pos + neg
    if total < min_reviews or total > max_reviews:
        return False
    ratio = pos / total if total else 0
    return ratio >= min_ratio


def gem_score(pos, neg):
    """Petit score pour trier les pépites entre elles : ratio d'abord, volume ensuite."""
    total = pos + neg
    ratio = pos / total if total else 0
    return round(ratio * 100 + log(total), 2)



# ----------------------------
# STEAMDB — most wished upcoming
# ----------------------------

STEAMDB_MOSTWISHED_URL = "https://steamdb.info/stats/mostwished/"


def _build_steamdb_url(min_release: str | None, max_release: str | None) -> str:
    from urllib.parse import urlencode
    params = {"displayOnly": "Game", "upcoming_only": "1"}
    if min_release:
        params["min_release"] = min_release
    if max_release:
        params["max_release"] = max_release
    return f"{STEAMDB_MOSTWISHED_URL}?{urlencode(params)}"


def _parse_steamdb_tbody(html_content: str) -> dict[str, int]:
    """
    Parse le HTML SteamDB Most Wished.
    Chaque <tr class="app" data-appid="..."> a en première <td data-sort="N">
    le rang global SteamDB (ex: 15, 31, 62...).
    Retourne {appid: steamdb_global_rank}.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    rows = soup.select("tr.app[data-appid]")
    if not rows:
        return {}

    rank_map: dict[str, int] = {}
    for row in rows:
        appid = row.get("data-appid", "").strip()
        if not appid:
            continue
        # Premier <td data-sort="N"> = rang global dans le classement SteamDB
        first_td = row.find("td", {"data-sort": True})
        if first_td:
            try:
                global_rank = int(first_td["data-sort"])
            except (ValueError, KeyError):
                continue
        else:
            continue
        rank_map[appid] = global_rank

    return rank_map


def scrape_steamdb_mostwished(
    min_release: str | None = None,
    max_release: str | None = None,
    quiet: bool = False,
) -> dict[str, int]:
    """
    Scrape SteamDB Most Wished (upcoming games) via Playwright non-headless
    (requis pour passer le Cloudflare managed challenge).

    Retourne {appid: steamdb_global_rank} ou dict vide en cas d'échec.
    Le rang est le rang global SteamDB (ex: 15 = 15e jeu le plus wishlisted
    sur Steam toutes sorties confondues) — plus petit = plus populaire.
    """
    url = _build_steamdb_url(min_release, max_release)

    if not quiet:
        print(f"  📡 SteamDB Most Wished → {url}")

    try:
        with sync_playwright() as p:
            # headless=False obligatoire : Cloudflare bloque le headless
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            try:
                page.wait_for_selector("tr.app[data-appid]", timeout=5000)
            except Exception:
                pass
            html_content = page.content()
            browser.close()
    except Exception as e:
        print(f"  ⚠️  SteamDB scrape failed ({e}) — section upcoming ignorée")
        return {}

    rank_map = _parse_steamdb_tbody(html_content)

    if not rank_map:
        print("  ⚠️  SteamDB: aucun jeu trouvé dans la page")
        return {}

    if not quiet:
        print(f"  ✅ SteamDB: {len(rank_map)} upcoming games (rangs {min(rank_map.values())}–{max(rank_map.values())})")

    return rank_map


def upcoming_steamdb_score(steamdb_rank: int) -> float:
    """Score basé sur le rang global SteamDB wishlist (plus petit = mieux)."""
    return round(100 / math.sqrt(steamdb_rank), 2)


# ----------------------------
# SCORING — coming soon
# ----------------------------

def _rank_points(rank: int | None) -> float:
    """Rang Steam → points. Le top 10 reste très dominant."""
    if not rank:
        return 0.0
    return 100 / math.sqrt(rank)


def upcoming_presale_score(appid: str, rankings: dict) -> float:
    """
    Score composite basé sur la position du jeu dans les filtres Steam
    upcoming / comingsoon / topsellers / popularnew.
    Le filtre `upcoming` (tri par popularité wishlist côté Steam) est le
    signal le plus fort ; les autres filtres apportent des bonus mineurs.
    """
    upcoming_rank   = rankings["upcoming"].get(appid)
    comingsoon_rank = rankings["comingsoon"].get(appid)
    topseller_rank  = rankings["topsellers"].get(appid)
    popularnew_rank = rankings["popularnew"].get(appid)

    if not upcoming_rank and not comingsoon_rank:
        return 0.0

    score = _rank_points(upcoming_rank)
    score += _rank_points(comingsoon_rank) * 0.25
    score += _rank_points(topseller_rank)  * 0.15
    score += _rank_points(popularnew_rank) * 0.05

    return round(score, 2)


def upcoming_sort_key(entry: dict) -> tuple:
    """
    Clé de tri unifiée pour la section upcoming.
    Priorité : score desc, puis rang SteamDB asc, puis rangs Steam asc.
    """
    return (
        -entry["score"],
        entry.get("steamdb_rank",    999999),
        entry.get("upcoming_rank",   999999),
        entry.get("comingsoon_rank", 999999),
        entry.get("topseller_rank",  999999),
    )

# ----------------------------
# AFFICHAGE
# ----------------------------

def print_section(title, items, quiet):
    if not quiet:
        print(f"\n{'='*60}")
        print(f"  {title}  ({len(items)} games)")
        print(f"{'='*60}\n")
    for i, g in enumerate(items, 1):
        desc = g.get("description")
        if not isinstance(desc, str):
            desc = ""
        tags_line = f"      🏷️  {g['tags']}\n" if g.get("tags") else ""
        gem_line = "💎" if g["is_gem"] else ""
        extra = ""
        if g["coming_soon"] and g.get("presale_breakdown"):
            extra = f"      📊 {g['presale_breakdown']}\n"
        print(
            f"{i:3d}. {g['name']}\n"
            f"      {gem_line} Release : {g['release']}\n"
            f"{tags_line}"
            f"{extra}"
            f"      📝 {desc}\n"
        )

def presale_breakdown(appid, rankings):
    parts = []
    r = rankings["upcoming"].get(appid)
    if r:
        parts.append(f"Upcoming #{r}")
    r = rankings["comingsoon"].get(appid)
    if r:
        parts.append(f"ComingSoon #{r}")
    r = rankings["topsellers"].get(appid)
    if r:
        parts.append(f"TopSeller #{r}")
    return " | ".join(parts)


# ----------------------------
# PIPELINE
# ----------------------------

def main():
    args = parse_args()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9,fr;q=0.8"
    }

    tag_list = load_tags(Path("steam_tags.json").expanduser().resolve())
    tag_map = build_tag_map(tag_list)

    if args.list_tags:
        for k in sorted(tag_map.keys()):
            print(k)
        return

    if not args.quiet:
        print("🎮 SteamDB Trending Engine\n")
        print(f"  Window   : {args.days} jours | Top releases : {args.top} | Top upcoming : {args.top_upcoming}")
        print(f"  Filters   : {', '.join(args.filters)} | Pages/filter : {args.pages}")
        if args.tags_include:
            print(f"  🏷️  Required tags : {', '.join(args.tags_include)}")
        if args.tags_exclude:
            print(f"  🚫 Excluded tags : {', '.join(args.tags_exclude)}")
        if args.no_cache:
            print("  ⚠️  Cache desactivated")
        print()

    conn, cursor = init_db(args.db, clear=args.clear_cache)
    if args.clear_cache and not args.quiet:
        print("🗑️  Cache cleaned\n")

    if not args.quiet:
        print("🔍 Collecting AppIDs...")
    
    appids, rankings = get_appids(
        args.filters,
        args.pages,
        args.rate_min,
        args.rate_max,
        args.quiet,
        tag_map,
        args.tags_include,
        headers
    )

    # -------------------------------------------------------
    # SteamDB Most Wished — source de rang wishlist pour l'upcoming
    # Lance un navigateur visible (headless=False) pour passer Cloudflare.
    # -------------------------------------------------------
    today = datetime.now().strftime("%Y-%m-%d")
    max_release = (datetime.now() + timedelta(days=args.upcoming_window_days)).strftime("%Y-%m-%d")
    steamdb_ranks = scrape_steamdb_mostwished(
        min_release=today,
        max_release=max_release,
        quiet=args.quiet,
    )
    # Ajouter les appids SteamDB au pool s'ils n'y sont pas déjà
    for wid in steamdb_ranks:
        if wid not in appids:
            appids.append(wid)

    SALE_EVENTS = {"Spring Sale", "Summer Sale", "Autumn Sale", "Winter Sale"}

    active_events = get_active_events({"User-Agent": "Mozilla/5.0"})
    demo_appid_map = {}  # appid du jeu de base -> appid de sa démo

    if active_events:
        print(f"\n🎉 Events Steam actifs : {', '.join(active_events)}\n")

        for event in active_events:
            if event == "Next Fest":
                print("  → Next Fest is LIVE! ajout des démos...")
                demo_entries = get_demos(STEAM_DEMOS)
                for entry in demo_entries:
                    appids.append(entry["demo_appid"])
                    demo_appid_map[entry["demo_appid"]] = entry["appid"]
                if not demo_entries:
                    print("  ⚠️  Aucune démo récupérée (page indisponible ou structure changée)")

            elif event in SALE_EVENTS:
                print(f"  → {event} is LIVE! ajout des jeux en promo...")
                sale_appids = get_sale_games()
                for appid in sale_appids:
                    if appid not in appids:
                        appids.append(appid)

        print()
    else:
        print("\nNo Steam event right now\n")

    is_sale_active = any(e in SALE_EVENTS for e in active_events)
    
    if not args.quiet:
        print(f"\n✅ {len(appids)} games collected\n")
        print("\nWriting to database and generating lists (this can take a few moments)...\n")

    released = []
    upcoming = []
    demos = []
    sales = []
    cutoff = datetime.now() - timedelta(days=args.days)

    recently_shown_upcoming = get_recently_shown_upcoming(cursor, args.upcoming_cooldown_days)
    if not args.quiet and args.upcoming_cooldown_days > 0:
        print(f"  🕓 {len(recently_shown_upcoming)} jeux 'upcoming' masqués (déjà montrés dans les {args.upcoming_cooldown_days} derniers jours)\n")

    # Instance Playwright partagée pour tous les appels get_steam_tags :
    # évite de relancer un navigateur (~2-5s) pour chaque jeu.
    with sync_playwright() as _pw:
        _tags_browser = _pw.chromium.launch(headless=True)
        _tags_page = _tags_browser.new_page()

        for appid in appids:
            details = get_details(
                appid,
                conn,
                cursor,
                args.rate_min,
                args.rate_max,
                args.no_cache,
                headers
            )

            if not details:
                continue

            name = details.get("name")
            if not name:
                continue

            asian_pattern = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]')

            if asian_pattern.search(name):
                continue

            price_overview = details.get("price_overview", {})
            discount = price_overview.get("discount_percent", 0)
            price = price_overview.get("final_formatted", "")
            release = parse_release_date(details.get("release_date", {}).get("date", ""))
            is_coming_soon = (
                details.get("release_date", {}).get("coming_soon", False)
                or appid in steamdb_ranks
            )

            if is_sale_active:
                if discount <= 0:
                    continue

            if details.get("type") == "demo":
                pass
            elif is_coming_soon:
                if release and release < cutoff:
                    continue
            elif release and release < cutoff:
                    continue
            elif details.get("type") != "demo" and details.get("type") != "game":
                continue

            pos, neg = get_review_breakdown(appid, conn, cursor, args.no_cache)
            total = pos + neg
            ratio = pos / total if total else 0
            if not is_coming_soon and details.get("type") != "demo" and ratio < args.min_reviews:
                continue

            # Filtre anti-répétition : un jeu upcoming déjà mis en avant récemment
            # est masqué pour laisser la place à de nouveaux titres.
            if is_coming_soon and appid in recently_shown_upcoming:
                if args.verbose:
                    print(f"  ⏭️  {name} — déjà montré récemment (cooldown upcoming)")
                continue

            # Pour les jeux sortis dans la fourchette "pépite indé" potentielle,
            # on va chercher le vrai ratio positif/négatif (appdetails ne donne
            # que le total, pas le détail).
            is_potential_gem = (
                not is_coming_soon
                and details.get("type") == "game"
                and args.gem_min_reviews <= pos + neg <= args.gem_max_reviews
            )

            tags = get_steam_tags(appid, conn, cursor, args.no_cache, _tags_page)

            if args.tags_exclude:
                if not tags_match(tags, args.tags_exclude):
                    if args.verbose:
                        print(f"  ✗ {name} — excluded tags")
                    continue

            # Directly get raw description
            desc = details.get("short_description", "")
            clean_desc = html.unescape(desc)

            header_img = details.get("header_image", "")
            entry = {
                "name": name,
                "appid": appid,
                "release": release.strftime("%Y-%m-%d") if release else "Upcoming",
                "recommendations": pos,
                "coming_soon": is_coming_soon,
                "tags": tags_display(details),
                "description": clean_desc,
                "price": price,
                "header": header_img,
                "is_gem": False
            }

            if details.get("type") == "demo":
                # `appid` ici est l'appid de la démo elle-même. On retrouve le
                # jeu parent via demo_appid_map pour récupérer sa vraie
                # description (plus informative que celle de la démo) et son
                # nom de jeu complet à afficher.
                parent_appid = demo_appid_map.get(appid)
                parent_details = None
                if parent_appid:
                    parent_details = get_details(
                        parent_appid,
                        conn,
                        cursor,
                        args.rate_min,
                        args.rate_max,
                        args.no_cache,
                        headers
                    )

                if parent_details:
                    parent_desc = parent_details.get("short_description", "")
                    entry["description"] = html.unescape(parent_desc)
                    entry["name"] = parent_details.get("name", name)
                    entry["appid"] = parent_appid

                demos.append(entry)
                if args.verbose:
                    print(f"  🔜 {entry['name']} (demo)")

            elif is_coming_soon:
                sdb_rank = steamdb_ranks.get(appid)
                if sdb_rank:
                    # Source primaire : rang global SteamDB wishlist
                    entry["score"] = upcoming_steamdb_score(sdb_rank)
                    entry["presale_breakdown"] = f"SteamDB Wishlist #{sdb_rank}"
                else:
                    # Fallback : scoring composite basé sur les filtres Steam
                    entry["score"] = upcoming_presale_score(appid, rankings)
                    entry["presale_breakdown"] = presale_breakdown(appid, rankings)
                entry["steamdb_rank"]    = sdb_rank if sdb_rank else 999999
                entry["upcoming_rank"]   = rankings["upcoming"].get(appid,   999999)
                entry["comingsoon_rank"] = rankings["comingsoon"].get(appid, 999999)
                entry["topseller_rank"]  = rankings["topsellers"].get(appid, 999999)

                upcoming.append(entry)
                if args.verbose:
                    print(f"  🔜 {name} (presale={entry['score']} — {entry['presale_breakdown']})")
            else:
                ref_date = release if release else datetime.now()
                entry["score"] = round(released_score(pos, neg, ref_date), 2)
                if args.verbose:
                    print(f"  ✓ {name} (score={entry['score']}, reviews={pos})")

                if is_potential_gem and is_gem(
                    pos, neg,
                    args.gem_min_reviews, args.gem_max_reviews,
                    args.gem_min_positive_ratio
                ):
                    entry["is_gem"] = True
                    if args.verbose:
                        print(f"  💎 {name} (pépite)")
                released.append(entry)

            if discount > 0:
                entry["discount"] = discount
                sales.append(entry)
                if args.verbose:
                    print(f"  ✓ {name} (sales)")

    # ----------------------------
    # CLASSEMENT
    # ----------------------------
    released.sort(key=lambda x: x["score"], reverse=True)
    upcoming.sort(key=upcoming_sort_key)

    top_released = released[:args.top]
    top_upcoming = upcoming[:args.top_upcoming]

    # On marque les upcoming affichés cette semaine pour les masquer
    # pendant la période de cooldown (évite de revoir les mêmes têtes
    # de classement la semaine suivante).
    if args.upcoming_cooldown_days > 0 and top_upcoming:
        mark_upcoming_shown(conn, cursor, [g["appid"] for g in top_upcoming])
        prune_upcoming_history(conn, cursor)

    if not args.quiet:
        print(f"  found {len(released)} released games | found {len(upcoming)} coming soon games \n")

    if top_released:
        print_section("🔥 TRENDING — Released games", top_released, args.quiet)
    else:
        print("\n  (No released game found)\n")

    if top_upcoming:
        print_section("🔜 PRESALE — Coming soon", top_upcoming, args.quiet)
    else:
        print("\n  (No coming soon game found)\n")

    if demos:
        print_section("DEMOS", demos, args.quiet)
    else:
        print("\n  (No game demos found)\n")
    
    if sales:
        print_section("💸 SALES", sales, args.quiet)
    else:
        print("\n  (No game sales found)\n")

    # ----------------------------
    # EXPORT CSV
    # ----------------------------

    if args.output:
        all_results = (
            [{**g, "section": "released"} for g in top_released] +
            [{**g, "section": "upcoming"} for g in top_upcoming] +
            [{**g, "section": "demos"} for g in demos] +
            [{**g, "section": "sales"} for g in sales]
        )
        fieldnames = ["section", "name", "appid", "release", "score",
                      "recommendations", "positive_ratio", "coming_soon", "tags", "description", "price", "header", "is_gem"]
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_results)
        print(f"\n💾 Exported results in {args.output}")

    conn.close()


if __name__ == "__main__":
    main()