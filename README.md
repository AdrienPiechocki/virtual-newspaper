# Virtual Newspaper — Générateur PDF

Assemble les CSV produits par les autres scripts du projet (RSS, Steam, LinkedIn jobs, météo)
en un PDF unique mis en page façon journal papier (A3, colonnes, filets, lettrine).

## Installation

```bash
pip install -r requirements.txt
```

## Utilisation

```bash
# lancer chaque générateur:
python -m scripts.articles.rss_reader https://www.lemonde.fr/rss/en_continu.xml https://www.franceinfo.fr/titres.rss
python -m scripts.linkedin.linkedin_scraper
python -m scripts.steam.steam_trending --no-cache
python -m scripts.forecast.weather_forecast

# fait pointer chaque script existant vers data/<nom>.csv, puis :
python generate_newspaper.py --data-dir data --output output/journal.pdf --masthead "L'Hebdo du Nerd"
```

## Personnalisation

- `templates/newspaper.css` : tout le style visuel (couleurs, polices, colonnes, filets)
- `templates/newspaper.html.j2` : structure des sections, ordre d'affichage
- `data_loader.py` : logique de tri/filtrage avant injection dans le template
