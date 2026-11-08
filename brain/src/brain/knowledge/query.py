"""The questions the Brain puts to its own knowledge base, made by code from an incident rather than written by a model."""

from __future__ import annotations


def incident_questions(incident_type: str, zone_name: str | None, actions: set[str]) -> list[str]:
    """Two to four plain questions about one incident: what to do, which procedure applies, and which procedures use what the Twin can do.

    The same incident and the same actions always give the same questions, in the same order.
    """
    where = f" in {zone_name}" if zone_name else ""
    questions = [f"What should be done about a {incident_type}{where}?", f"Which procedure applies to a {incident_type} incident?"]
    questions += [f"Which procedure uses {action.replace('_', ' ')} for a {incident_type}?" for action in sorted(actions)[:2]]
    return questions
