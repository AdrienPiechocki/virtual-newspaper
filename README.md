# Virtual Newspaper — Générateur PDF

Assemble les CSV produits par les autres scripts du projet (RSS, Steam, LinkedIn jobs, météo)
en un PDF unique mis en page façon journal papier (A3, colonnes, filets, lettrine).

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

## Utilisation

```bash
./run.sh
```

## Personnalisation

- `templates/newspaper.css` : tout le style visuel (couleurs, polices, colonnes, filets)
- `templates/newspaper.html.j2` : structure des sections, ordre d'affichage
- `data_loader.py` : logique de tri/filtrage avant injection dans le template
