#!/usr/bin/env python3
"""
Colonnes attendues dans le CSV:
    titre     : titre de l'article (obligatoire)
    corps     : texte principal de l'article (obligatoire)
    rubrique  : section (ex: POLITIQUE, SPORT...) — optionnel
    auteur    : byline — optionnel
    chapeau   : texte d'accroche en italique — optionnel
    taille    : 'grande', 'moyenne', 'petite' — optionnel (défaut: 'moyenne')
               grande  → pleine largeur, titre XXL
               moyenne → demi-page, titre L
               petite  → 1 colonne, titre M
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BalancedColumns,
    CondPageBreak,
    FrameBreak,
    HRFlowable,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)
from reportlab.platypus.frames import Frame
from reportlab.platypus.tableofcontents import TableOfContents

# ─── Dimensions page ───────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN_TOP    = 2.8 * cm
MARGIN_BOTTOM = 2.0 * cm
MARGIN_LEFT   = 1.5 * cm
MARGIN_RIGHT  = 1.5 * cm
GUTTER        = 0.4 * cm   # espace entre colonnes
NB_COLS       = 4

# Largeur utile et largeur d'une colonne
BODY_W = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT
COL_W  = (BODY_W - (NB_COLS - 1) * GUTTER) / NB_COLS

# ─── Palette ───────────────────────────────────────────────────────────────────
BLACK     = colors.black
DARK_GRAY = colors.HexColor("#222222")
MID_GRAY  = colors.HexColor("#555555")
LIGHT_GRAY= colors.HexColor("#999999")
RULE_COLOR= colors.black
RUBRIQUE_COLOR = colors.HexColor("#b22222")  # rouge presse

# ─── Styles typographiques ─────────────────────────────────────────────────────
def make_styles():
    s = getSampleStyleSheet()

    base = dict(fontName="Times-Roman", textColor=DARK_GRAY)

    styles = {
        # Titre du journal (bandeau)
        "journal_name": ParagraphStyle(
            "journal_name",
            fontName="Times-Bold", fontSize=42, leading=48,
            textColor=BLACK, alignment=TA_CENTER,
        ),
        "journal_date": ParagraphStyle(
            "journal_date",
            fontName="Times-Italic", fontSize=9, leading=12,
            textColor=MID_GRAY, alignment=TA_CENTER,
        ),
        # Rubriques
        "rubrique": ParagraphStyle(
            "rubrique",
            fontName="Helvetica-Bold", fontSize=7.5, leading=10,
            textColor=RUBRIQUE_COLOR, spaceBefore=2, spaceAfter=1,
        ),
        # Titres d'articles
        "titre_grande": ParagraphStyle(
            "titre_grande",
            fontName="Times-Bold", fontSize=28, leading=32,
            textColor=BLACK, spaceAfter=4, alignment=TA_LEFT,
        ),
        "titre_moyenne": ParagraphStyle(
            "titre_moyenne",
            fontName="Times-Bold", fontSize=18, leading=22,
            textColor=BLACK, spaceAfter=3, alignment=TA_LEFT,
        ),
        "titre_petite": ParagraphStyle(
            "titre_petite",
            fontName="Times-Bold", fontSize=13, leading=16,
            textColor=BLACK, spaceAfter=2, alignment=TA_LEFT,
        ),
        # Chapeau (lead)
        "chapeau": ParagraphStyle(
            "chapeau",
            fontName="Times-Italic", fontSize=10.5, leading=14,
            textColor=DARK_GRAY, spaceAfter=4,
        ),
        # Byline
        "auteur": ParagraphStyle(
            "auteur",
            fontName="Helvetica", fontSize=7.5, leading=10,
            textColor=LIGHT_GRAY, spaceAfter=3,
        ),
        # Corps de texte
        "corps": ParagraphStyle(
            "corps",
            **base, fontSize=9.5, leading=13.5,
            spaceAfter=0, alignment=TA_JUSTIFY,
            firstLineIndent=12,
        ),
    }
    return styles


# ─── En-tête de journal (dessiné sur le canvas) ───────────────────────────────
class BandeauNewspaper:
    """Dessiné via onFirstPage / onLaterPages."""

    def __init__(self, nom_journal, date_str, numero):
        self.nom = nom_journal
        self.date = date_str
        self.numero = numero

    def draw(self, c: canvas.Canvas, doc):
        w, h = A4
        y_top = h - 0.8 * cm

        # Filet supérieur épais
        c.setStrokeColor(BLACK)
        c.setLineWidth(2.5)
        c.line(MARGIN_LEFT, y_top, w - MARGIN_RIGHT, y_top)

        # Nom du journal
        c.setFont("Times-Bold", 42)
        c.setFillColor(BLACK)
        c.drawCentredString(w / 2, y_top - 1.3 * cm, self.nom)

        # Ligne fine sous le titre
        c.setLineWidth(0.8)
        c.line(MARGIN_LEFT, y_top - 1.7 * cm, w - MARGIN_RIGHT, y_top - 1.7 * cm)

        # Date et numéro
        c.setFont("Times-Italic", 8.5)
        c.setFillColor(MID_GRAY)
        c.drawString(MARGIN_LEFT, y_top - 2.1 * cm, self.date)
        c.drawRightString(w - MARGIN_RIGHT, y_top - 2.1 * cm, f"N° {self.numero}")

        # Filet de séparation bas
        c.setLineWidth(1.5)
        c.setStrokeColor(BLACK)
        c.line(MARGIN_LEFT, y_top - 2.5 * cm, w - MARGIN_RIGHT, y_top - 2.5 * cm)

        # Numéro de page (sauf première)
        if doc.page > 1:
            c.setFont("Times-Roman", 8)
            c.setFillColor(MID_GRAY)
            c.drawCentredString(w / 2, MARGIN_BOTTOM * 0.4, f"— {doc.page} —")


# ─── Construction des blocs d'article ─────────────────────────────────────────
def build_article_flowables(article: dict, styles: dict, width: float) -> list:
    """
    Convertit un dict d'article en liste de Flowables ReportLab.
    `width` est la largeur disponible (pour choisir le style de titre).
    """
    taille = article.get("taille", "moyenne").strip().lower()
    if taille not in ("grande", "moyenne", "petite"):
        taille = "moyenne"

    blocs = []

    # Rubrique
    if article.get("rubrique"):
        blocs.append(Paragraph(article["rubrique"].upper(), styles["rubrique"]))

    # Titre
    titre_style = styles[f"titre_{taille}"]
    blocs.append(Paragraph(article["titre"], titre_style))

    # Auteur
    if article.get("auteur"):
        blocs.append(Paragraph(f"Par {article['auteur']}", styles["auteur"]))

    # Filet sous le titre
    blocs.append(HRFlowable(width=width, thickness=0.5, color=LIGHT_GRAY, spaceAfter=4, spaceBefore=1))

    # Chapeau
    if article.get("chapeau"):
        blocs.append(Paragraph(article["chapeau"], styles["chapeau"]))

    # Corps
    corps = article.get("corps", "").strip()
    if corps:
        # Découpage en paragraphes si séparés par \n
        for para in corps.split("\n"):
            para = para.strip()
            if para:
                blocs.append(Paragraph(para, styles["corps"]))

    return blocs


def build_article_block(article: dict, styles: dict, available_width: float) -> list:
    """
    Retourne les flowables d'un article encapsulés dans un KeepTogether
    suivi d'un séparateur.
    """
    inner = build_article_flowables(article, styles, available_width)
    block = [KeepTogether(inner)]
    block.append(Spacer(1, 0.3 * cm))
    block.append(HRFlowable(
        width=available_width, thickness=1.2, color=BLACK,
        spaceAfter=6, spaceBefore=2,
    ))
    return block


# ─── Mise en page multi-colonnes ──────────────────────────────────────────────
def compose_page(articles: list, styles: dict) -> list:
    """
    Organise les articles en sections :
      - Les articles 'grande' occupent la pleine largeur (BalancedColumns 4 cols)
      - Les articles 'moyenne' occupent 2 colonnes (BalancedColumns 2 cols)
      - Les articles 'petite' s'intègrent en 1 colonne
    On regroupe les 'petites' ensemble dans une zone 4-colonnes.
    """
    story = []

    grandes  = [a for a in articles if a.get("taille", "").lower() == "grande"]
    moyennes = [a for a in articles if a.get("taille", "").lower() == "moyenne"]
    petites  = [a for a in articles if a.get("taille", "").lower() not in ("grande", "moyenne")]

    col_spec_4 = [(BODY_W, NB_COLS, GUTTER)]   # 4 colonnes
    col_spec_2 = [(BODY_W, 2, GUTTER)]           # 2 colonnes

    # ── Articles à la une (grande) ────────────────────────────────────────────
    for art in grandes:
        inner = build_article_flowables(art, styles, BODY_W / NB_COLS - GUTTER)
        bc = BalancedColumns(
            inner,
            nCols=NB_COLS,
            needed=3 * cm,
            spaceBefore=0,
            spaceAfter=0.2 * cm,
        )
        story.append(bc)
        story.append(HRFlowable(width=BODY_W, thickness=1.5, color=BLACK, spaceAfter=6, spaceBefore=4))

    # ── Articles moyens (2 colonnes) ──────────────────────────────────────────
    if moyennes:
        half_w = (BODY_W - GUTTER) / 2 - GUTTER / 2

        # On regroupe les articles moyens par paires côte à côte avec BalancedColumns
        pairs = [moyennes[i:i+2] for i in range(0, len(moyennes), 2)]
        for pair in pairs:
            # Chaque paire : les articles s'enchaînent dans 2 colonnes équilibrées
            inner = []
            for art in pair:
                inner += build_article_flowables(art, styles, half_w)
                inner.append(Spacer(1, 0.4 * cm))
                inner.append(HRFlowable(width=half_w, thickness=0.7, color=LIGHT_GRAY, spaceAfter=4, spaceBefore=2))

            bc = BalancedColumns(
                inner,
                nCols=2,
                needed=3 * cm,
                spaceBefore=0,
                spaceAfter=0.2 * cm,
            )
            story.append(bc)
            story.append(HRFlowable(width=BODY_W, thickness=1.5, color=BLACK, spaceAfter=6, spaceBefore=4))

    # ── Brèves / petits articles (4 colonnes) ─────────────────────────────────
    if petites:
        small_w = COL_W - GUTTER / 2
        inner = []
        for art in petites:
            inner += build_article_flowables(art, styles, small_w)
            inner.append(Spacer(1, 0.3 * cm))
            inner.append(HRFlowable(width=small_w, thickness=0.7, color=LIGHT_GRAY, spaceAfter=4, spaceBefore=2))

        bc = BalancedColumns(
            inner,
            nCols=NB_COLS,
            needed=2 * cm,
            spaceBefore=0,
            spaceAfter=0,
        )
        story.append(bc)

    return story


# ─── Chargement CSV ───────────────────────────────────────────────────────────
def load_csv(path: str) -> list:
    articles = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normaliser les clés (strip espaces)
            article = {k.strip(): v.strip() for k, v in row.items() if k}
            if article.get("titre") and article.get("corps"):
                articles.append(article)
    return articles


# ─── Génération du PDF ────────────────────────────────────────────────────────
def generate_pdf(
    csv_files: list,
    output: str = "journal.pdf",
    nom_journal: str = "Le Quotidien",
    numero: int = 1,
):
    # Charger tous les articles
    articles = []
    for f in csv_files:
        try:
            loaded = load_csv(f)
            articles.extend(loaded)
            print(f"  ✓ {len(loaded)} articles chargés depuis '{f}'")
        except FileNotFoundError:
            print(f"  ✗ Fichier introuvable : {f}", file=sys.stderr)

    if not articles:
        print("Aucun article à composer. Abandon.", file=sys.stderr)
        sys.exit(1)

    date_str = datetime.now().strftime("%-d %B %Y").capitalize()
    # Python < 3.12 : %-d fonctionne sur Linux ; fallback
    try:
        date_str = datetime.now().strftime("%-d %B %Y")
    except ValueError:
        date_str = datetime.now().strftime("%d %B %Y").lstrip("0")

    bandeau = BandeauNewspaper(nom_journal, date_str, numero)
    styles  = make_styles()

    # Document
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"{nom_journal} — {date_str}",
        author=nom_journal,
    )

    def on_page(c, d):
        bandeau.draw(c, d)

    story = compose_page(articles, styles)

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"\n✅  PDF généré : {output}  ({len(articles)} articles)")


# ─── Point d'entrée ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Génère un PDF style journal papier à partir de CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("csv_files", nargs="+", metavar="CSV", help="Fichiers CSV d'articles")
    parser.add_argument("--output", "-o", default="journal.pdf", help="Nom du fichier PDF de sortie")
    parser.add_argument("--titre", "-t", default="Le Quotidien", help="Nom du journal")
    parser.add_argument("--numero", "-n", type=int, default=1, help="Numéro d'édition")
    args = parser.parse_args()

    print(f"🗞  Composition de '{args.titre}' n°{args.numero}...")
    generate_pdf(args.csv_files, args.output, args.titre, args.numero)


if __name__ == "__main__":
    main()