"""Domeinregels voor de examenworkflow.

Alle stappen staan hier op één centrale plek. De volgorde is afgeleid van de
functionele blauwdruk. Door afhankelijkheden expliciet te maken, kan een
wijziging in een eerdere fase nooit stilzwijgend een verouderde latere
goedkeuring laten staan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class WorkflowStep:
    """Een stap in de vaste verwerkingsvolgorde.

    ``requires`` bevat de sleutels van stappen die eerst afgerond moeten zijn.
    De applicatie gebruikt deze informatie zowel voor de gebruikersinterface
    als voor server-side validatie; de browser kan de volgorde dus niet omzeilen.
    """

    key: str
    title: str
    description: str
    requires: tuple[str, ...] = ()


WORKFLOW: tuple[WorkflowStep, ...] = (
    WorkflowStep("metadata", "Import en documenteigenschappen", "Documenten groeperen en metadata eenmalig bevestigen."),
    WorkflowStep("opgaven_starts", "Vraagstarts opgaven", "Vraagstarts detecteren, toevoegen, verwijderen en verplaatsen.", ("metadata",)),
    WorkflowStep("opgaven_fragments", "Vraagfragmenten opgaven", "Fragmentgrenzen bepalen en visueel controleren.", ("opgaven_starts",)),
    WorkflowStep("opgaven_analyse", "Vraagtype, punten en opties", "Vraagtype, maximumscore en antwoordopties controleren.", ("opgaven_fragments",)),
    WorkflowStep("uitwerk_starts", "Vraagstarts uitwerkbijlage", "De structuur van de uitwerkbijlage controleren.", ("metadata",)),
    WorkflowStep("uitwerk_fragments", "Fragmenten uitwerkbijlage", "Fragmenten maken en aan vragen koppelen.", ("uitwerk_starts",)),
    WorkflowStep("cv_starts", "Vraagstarts correctievoorschrift", "Vraagstarts in het correctievoorschrift controleren.", ("metadata",)),
    WorkflowStep("cv_fragments", "Correctievoorschrift verwerken", "Opschonen, uitsnijden en pagina's verticaal samenvoegen.", ("cv_starts",)),
    # De aanvulling is een volwaardig brondocument. Eerst worden de vraagstarts\n    # gecontroleerd, daarna de uitsneden. Pas daarna beslist de docent per\n    # fragment of het een aanvulling, vervanging of irrelevante passage is.\n    WorkflowStep("supplement_starts", "Vraagstarts CV-aanvulling", "Vraagstarts in de aanvulling detecteren en visueel controleren.", ("metadata", "cv_fragments")),\n    WorkflowStep("supplement_fragments", "Fragmenten CV-aanvulling", "De aanvulling uitsnijden tot vraagfragmenten en de grenzen controleren.", ("supplement_starts",)),\n    WorkflowStep("cv_aanvulling", "Aanvulling samenvoegen", "Per gecontroleerd fragment aanvullen, vervangen of negeren.", ("supplement_fragments",)),\n    WorkflowStep("antwoorden", "Antwoorden herkennen", "Gesloten antwoordvormen en juiste antwoorden koppelen.", ("opgaven_analyse", "cv_fragments", "cv_aanvulling")),
    WorkflowStep("relaties", "Aanvullende controles", "Nummering, documentkoppelingen, maximumscores en volledigheid automatisch controleren; alleen afwijkingen vragen aandacht.", ("uitwerk_fragments", "cv_aanvulling", "antwoorden")),
    WorkflowStep("snippets", "Definitieve snippets genereren", "Pas na de controles alle definitieve afbeeldingen uitsnijden.", ("relaties",)),
    WorkflowStep("eindcontrole", "Integrale eindcontrole", "Per vraag alle bronnen en antwoorden in samenhang controleren.", ("snippets",)),
    WorkflowStep("publicatie", "Publiceren in examenbibliotheek", "Alleen een volledig en gecontroleerd examen publiceren.", ("eindcontrole",)),
)

STEP_BY_KEY = {step.key: step for step in WORKFLOW}


def unmet_requirements(step_key: str, completed: Iterable[str]) -> list[str]:
    """Geef de nog niet afgeronde voorgangers van een workflowstap terug."""
    step = STEP_BY_KEY[step_key]
    done = set(completed)
    return [key for key in step.requires if key not in done]


def invalidate_dependents(changed_key: str) -> list[str]:
    """Bepaal transitief welke stappen opnieuw gecontroleerd moeten worden.

    De gewijzigde stap zelf wordt niet opgenomen: die wordt opnieuw uitgevoerd.
    Een breadth-first traversal voorkomt dat een afhankelijke stap die via
    meerdere routes bereikbaar is dubbel wordt geretourneerd.
    """
    invalid = set()
    frontier = [changed_key]
    while frontier:
        current = frontier.pop(0)
        for step in WORKFLOW:
            if current in step.requires and step.key not in invalid:
                invalid.add(step.key)
                frontier.append(step.key)
    return [step.key for step in WORKFLOW if step.key in invalid]
