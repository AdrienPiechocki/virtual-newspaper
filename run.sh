#!/bin/bash
set -e

cd "$(dirname "$0")"

source .venv/bin/activate

python -m scripts.articles.rss_reader https://www.lemonde.fr/rss/en_continu.xml https://www.franceinfo.fr/titres.rss
python -m scripts.linkedin.linkedin_scraper
python -m scripts.steam.steam_trending --no-cache
python -m scripts.forecast.weather_forecast

DATE=$(date +%Y-%m-%d)

OUTPUT_FILE="output/LHebdoDuNerd-${DATE}.pdf"

python generate_newspaper.py \
    --data-dir data \
    --output "$OUTPUT_FILE" \
    --masthead "L'Hebdo du Nerd"

curl --fail \
     -u "$NEXTCLOUD_USER:$NEXTCLOUD_APP_PASSWORD" \
     -T "$OUTPUT_FILE" \
     "https://${NEXTCLOUD_DOMAIN}/remote.php/dav/files/$NEXTCLOUD_USER/L%27Hebdo%20du%20Nerd/$(basename "$OUTPUT_FILE")"