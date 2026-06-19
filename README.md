# Virtual Newspaper — Générateur PDF

Assemble les CSV produits par les autres scripts du projet (RSS, Steam, LinkedIn jobs, météo)
en un PDF unique mis en page façon journal papier (A3, colonnes, filets, lettrine).

## Installation

```bash
git clone https://github.com/AdrienPiechocki/virtual-newspaper.git
cd virtual-newspaper
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Si besoin de l'intégration avec Nextcloud, ajoutez un .env avec les bonnes valeurs
```bash
export NEXTCLOUD_USER="user"
export NEXTCLOUD_APP_PASSWORD="XXXXXXXXXXXXXXXXXXXXXXX"
export NEXTCLOUD_DOMAIN="nextcloud.domain.fr"
```

## Utilisation

```bash
./run.sh
```

## Personnalisation

- `templates/newspaper.css` : tout le style visuel (couleurs, polices, colonnes, filets)
- `templates/newspaper.html.j2` : structure des sections, ordre d'affichage
- `data_loader.py` : logique de tri/filtrage avant injection dans le template
