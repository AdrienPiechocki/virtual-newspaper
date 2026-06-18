#!/bin/bash
set -e

cd "$(dirname "$0")"

source .venv/bin/activate

python -m scripts.articles.rss_reader https://www.lemonde.fr/rss/en_continu.xml https://www.franceinfo.fr/titres.rss
python -m scripts.linkedin.linkedin_scraper
python -m scripts.steam.steam_trending --clear-cache
python -m scripts.forecast.weather_forecast

DATE=$(date +%Y-%m-%d)

OUTPUT_FILE="output/LHebdoDuNerd-${DATE}.pdf"

python generate_newspaper.py \
    --data-dir data \
    --output "output/Journal.pdf" \
    --masthead "L'Hebdo du Nerd"

curl --fail \
     -u "$NEXTCLOUD_USER:$NEXTCLOUD_APP_PASSWORD" \
     -T "output/Journal.pdf" \
     "https://${NEXTCLOUD_DOMAIN}/remote.php/dav/files/$NEXTCLOUD_USER/L%27Hebdo%20du%20Nerd/$(basename "$OUTPUT_FILE")"
     
# Garder uniquement les 5 derniers journaux sur Nextcloud
NEXTCLOUD_DIR_URL="https://${NEXTCLOUD_DOMAIN}/remote.php/dav/files/$NEXTCLOUD_USER/L%27Hebdo%20du%20Nerd/"

curl -s -u "$NEXTCLOUD_USER:$NEXTCLOUD_APP_PASSWORD" \
     -X PROPFIND \
     -H "Depth: 1" \
     "$NEXTCLOUD_DIR_URL" \
  | grep -oP '(?<=<d:href>)[^<]+' \
  | grep '\.pdf' \
  | sort \
  | head -n -5 \
  | while read -r filepath; do
      filename=$(basename "$filepath")
      decoded_filename=$(python3 -c "import urllib.parse,sys; print(urllib.parse.unquote(sys.argv[1]))" "$filename")
      echo "Suppression de l'ancien journal : $decoded_filename"
      curl -s -u "$NEXTCLOUD_USER:$NEXTCLOUD_APP_PASSWORD" \
           -X DELETE \
           "https://${NEXTCLOUD_DOMAIN}/remote.php/dav/files/$NEXTCLOUD_USER/L%27Hebdo%20du%20Nerd/$filename"
    done
