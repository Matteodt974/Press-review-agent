"""Génération du rapport Word (.docx)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import docx
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from .models import Affaire, Article, Verdict

log = logging.getLogger(__name__)


@dataclass
class ReportData:
    since: datetime
    now: datetime
    last_run: datetime | None
    premier_lancement: bool
    plafonnee: bool
    max_days: int
    affaires: list[Affaire] = field(default_factory=list)
    resume_global: str = ""
    stats: dict = field(default_factory=dict)
    echecs: list[str] = field(default_factory=list)
    exclus: list[tuple[Article, Verdict]] = field(default_factory=list)
    mode_hors_ligne: bool = False
    collecte_echouee: bool = False  # aucune source n'a répondu


def _add_hyperlink(paragraph, url: str, text: str):
    part = paragraph.part
    r_id = part.relate_to(url, docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    rpr.append(color)
    rpr.append(underline)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def _label(p, label: str, value: str):
    r = p.add_run(label)
    r.bold = True
    p.add_run(value)


def write_report(data: ReportData, out_dir: Path, tz_name: str = "America/Toronto",
                 annexe_exclus_max: int = 60) -> Path:
    tz = ZoneInfo(tz_name)
    fmt = lambda d: d.astimezone(tz).strftime("%d/%m/%Y %H:%M")
    doc = docx.Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)

    doc.add_heading("Revue de presse — Briefs de sécurité", level=0)
    p = doc.add_paragraph()
    _label(p, "Période couverte : ", f"du {fmt(data.since)} au {fmt(data.now)}")
    if data.premier_lancement:
        doc.add_paragraph(f"Premier lancement : recherche limitée aux {data.max_days} derniers jours.")
    elif data.plafonnee and data.last_run:
        doc.add_paragraph(f"Dernier lancement le {fmt(data.last_run)} : recherche plafonnée "
                          f"aux {data.max_days} derniers jours.")
    if data.mode_hors_ligne:
        w = doc.add_paragraph().add_run("MODE HORS LIGNE (FakeLLM) : classement par mots-clés, "
                                        "résumés non rédigés par l'IA. Ne pas diffuser.")
        w.bold = True
        w.font.highlight_color = WD_COLOR_INDEX.YELLOW

    # ---------- Collecte impossible / rien de nouveau ----------
    if data.collecte_echouee:
        doc.add_heading("Résultat", level=1)
        r = doc.add_paragraph().add_run(
            "ÉCHEC DE LA COLLECTE : aucune source n'a répondu (connexion internet, pare-feu ou "
            "proxy ?). Ce rapport ne permet PAS de conclure qu'il n'y a rien de nouveau. "
            "La date du dernier lancement n'a pas été mise à jour.")
        r.bold = True
        r.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
    elif not data.affaires:
        doc.add_heading("Résultat", level=1)
        r = doc.add_paragraph().add_run(
            f"Aucun nouvel article trouvé depuis le {data.since.astimezone(tz):%d/%m/%Y}.")
        r.bold = True
    else:
        nq = sum(a.portee == "Québec" for a in data.affaires)
        doc.add_heading("Synthèse", level=1)
        doc.add_paragraph(f"{len(data.affaires)} affaire(s) retenue(s) : {nq} au Québec, "
                          f"{len(data.affaires) - nq} ailleurs au Canada.")
        if data.resume_global:
            doc.add_paragraph(data.resume_global)

        doc.add_heading("Affaires (par ordre d'importance)", level=1)
        for i, a in enumerate(data.affaires, start=1):
            doc.add_heading(f"{i}. {a.titre}", level=2)
            p = doc.add_paragraph()
            _label(p, "Portée : ", a.portee)
            p.add_run("   |   ")
            _label(p, "Stade : ", a.stade)
            p.add_run("   |   ")
            _label(p, "Importance : ", f"{a.importance}/5")
            doc.add_paragraph(a.resume)
            p = doc.add_paragraph()
            _label(p, f"Média(s) ({len(a.medias)}) : ", ", ".join(a.medias))
            doc.add_paragraph().add_run("Liens :").bold = True
            for art in a.articles:
                lp = doc.add_paragraph(style="List Bullet")
                lp.add_run(f"{art.media} ({art.published.astimezone(tz):%d/%m/%Y}) — ")
                _add_hyperlink(lp, art.url, art.title)

    # ---------- Annexes ----------
    doc.add_heading("Notes méthodologiques", level=1)
    s = data.stats
    doc.add_paragraph(
        f"Articles récupérés : {s.get('recus', 0)} ; dans la période : {s.get('dans_fenetre', 0)} ; "
        f"uniques : {s.get('uniques', 0)} ; analysés par l'IA : {s.get('candidats', 0)} ; "
        f"jugés pertinents : {s.get('pertinents', 0)}."
    )
    if s.get("tronques"):
        doc.add_paragraph(f"ATTENTION : {s['tronques']} article(s) non analysé(s) (plafond de coût atteint).")
    if s.get("non_classes"):
        doc.add_paragraph(f"ATTENTION : {s['non_classes']} article(s) non classé(s) par l'IA.")
    if s.get("sans_date"):
        doc.add_paragraph(f"{s['sans_date']} article(s) ignoré(s) car sans date de publication.")
    doc.add_paragraph(
        "Résumés rédigés à partir des titres et chapôs publics (pas d'accès aux articles "
        "payants). Les flux RSS ne conservent que quelques jours d'articles : sur une longue "
        "période, la couverture repose surtout sur la recherche Google News et peut être incomplète."
    )
    if data.echecs:
        doc.add_paragraph().add_run(f"Sources en échec ({len(data.echecs)}) :").bold = True
        for e in data.echecs:
            doc.add_paragraph(e, style="List Bullet")

    if data.exclus:
        doc.add_heading("Annexe — Articles écartés par l'IA (pour validation)", level=1)
        doc.add_paragraph("Articles passés par le filtre de mots-clés mais jugés non pertinents. "
                          "Signale tout article qui aurait dû être retenu : c'est ce qui sert à "
                          "améliorer le filtre.")
        for art, v in data.exclus[:annexe_exclus_max]:
            lp = doc.add_paragraph(style="List Bullet")
            lp.add_run(f"[{art.media}] ")
            _add_hyperlink(lp, art.url, art.title)
            r = lp.add_run(f" — critère {v.critere or '–'} : {v.justification}")
            r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        if len(data.exclus) > annexe_exclus_max:
            doc.add_paragraph(f"... et {len(data.exclus) - annexe_exclus_max} autre(s).")

    return _save(doc, out_dir, data.now.astimezone(tz))


def _save(doc, out_dir: Path, local_now: datetime) -> Path:
    path = out_dir / f"revue_securite_{local_now:%Y-%m-%d}.docx"
    if path.exists():
        path = out_dir / f"revue_securite_{local_now:%Y-%m-%d_%Hh%M}.docx"
    try:
        doc.save(path)
    except PermissionError:  # fichier ouvert dans Word
        path = out_dir / f"revue_securite_{local_now:%Y-%m-%d_%Hh%M%S}.docx"
        doc.save(path)
    return path
