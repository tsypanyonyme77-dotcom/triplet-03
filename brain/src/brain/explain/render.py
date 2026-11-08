"""An explanation in words. The text is made by code from the facts; a model may rephrase the one-line version, and its answer is
thrown away if it adds a number or an identifier the facts do not hold."""

from __future__ import annotations

import re
from collections.abc import Callable

from brain.explain.models import Explanation

LAYER_NAME = {"twin": "Twin", "guardian": "Guardian", "brain": "Brain"}
SUBJECT = {"decision": "Decision", "held": "Held action", "incident": "Incident"}
MAX_WORDS = 25

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_IDENT = re.compile(r"\b(?:unit|verdict|dec|inc|cit|zone|call|police|fire|amb)-[\w-]+|[\w-]+#\d+|\b[A-Z]{2,}-(?:PB-)?\d+\b")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _at(ms: int) -> str:
    return f"+{ms / 1000:.2f} s"


def to_markdown(e: Explanation) -> str:
    out = [f"# {e.headline}", ""]
    source = f"built from the log (chain head {e.log_chain_head[:8]})" if e.log_chain_head else "built from the live log"
    out += [f"*{SUBJECT[e.subject]} {e.id}, {source}*", ""]
    if e.subject == "held":
        failed = next((c for c in reversed(e.checks) if not c.passed), None)
        out += ["## Why it was held", ""]
        if failed:
            out.append(f"- **{failed.check}**: {failed.reason}")
        out += [f"- {c.change}: {'it would have gone through' if c.would_flip else 'it would not have helped'}." for c in e.counterfactuals]
        out.append("")
    out += ["## What happened", ""]
    out += [f"{s.n}. **{_at(s.at_ms)}** · {LAYER_NAME[s.layer]} · {s.region} — {s.fact}" for s in e.steps]
    if e.checks:
        out += ["", "## At the gate", ""]
        out += [f"- {'Passed' if c.passed else 'Held'}: {c.check} — {c.reason}" for c in e.checks]
    if e.knowledge:
        out += ["", "## What it relied on", ""]
        out += [f"- {k.id} ({k.kind}){': ' + k.title if k.title else ''}" for k in e.knowledge]
    if e.margins:
        out += ["", "## How close it was", ""]
        out += [f"- {m.name}: {m.how_close}" for m in e.margins]
    if e.alternatives:
        out += ["", "## What else was on the table", ""]
        out += [f"- {a.name}{' (chosen)' if a.chosen else ''}: {a.rationale}" for a in e.alternatives]
    if e.counterfactuals and e.subject != "held":
        out += ["", "## What would have changed it", ""]
        out += [f"- {c.change}: it would {'have been held' if c.would_flip else 'not have mattered'}. ({c.basis})" for c in e.counterfactuals]
    if e.unresolved:
        out += ["", "## Not accounted for", ""]
        out += [f"- {item} is named but the log has no record of it" for item in e.unresolved]
    return "\n".join(out) + "\n"


def _clip(text: str) -> str:
    words = text.split()
    return text if len(words) <= MAX_WORDS else " ".join(words[: MAX_WORDS - 1]).rstrip(",;:.") + "…"


def to_sentence(e: Explanation) -> str:
    """One sentence for the caption: at most 25 words."""
    if e.subject == "incident":
        return _clip(e.headline)
    what = e.headline.split(":")[0] if e.subject == "decision" else e.headline.removeprefix("Held: ").split(". ")[0]
    if e.subject == "decision":
        sources = next((m for m in e.margins if m.name == "independent sources"), None)
        tail = f"; it passed {_plural(len(e.checks), 'gate check')}"
        if sources:
            tail += f" on {_plural(int(sources.observed), 'independent trusted source')}"
        return _clip(f"{what}{tail if e.checks else ''}.")
    failed = next((c for c in reversed(e.checks) if not c.passed), None)
    sources = next((m for m in e.margins if m.name == "independent sources"), None)
    if failed and failed.check == "evidence" and sources:
        why = f"{_plural(int(sources.observed), 'independent trusted source')} found, {int(sources.threshold)} needed"
    elif failed and failed.check == "human_approval":
        why = "it needs a human approval, which is not wired up yet"
    elif failed and failed.check == "trust":
        why = "the evidence was not trusted"
    else:
        why = (failed.reason if failed else "a check failed").split(". ")[0]
    return _clip(f"Held: {what[0].lower()}{what[1:]}; {why}.")


def narrate(e: Explanation, ask: Callable[[str], str] | None) -> tuple[str, str]:
    """(text, "llm" or "template"). The model's text must add no figure and no identifier that the explanation does not hold."""
    fallback = (to_sentence(e), "template")
    if ask is None:
        return fallback
    facts = to_markdown(e)
    prompt = ("Rewrite these facts as at most two short, plain sentences for a city official. Use only the numbers and names "
              f"given. Do not add anything.\n\n{facts}")
    try:
        reply = " ".join(ask(prompt).split())
    except Exception:  # noqa: BLE001 - a sentence that cannot be built falls back to the plain one
        return fallback
    if not reply or len(reply.split()) > 60:
        return fallback
    if not set(_NUMBER.findall(reply)) <= set(_NUMBER.findall(facts)) or not set(_IDENT.findall(reply)) <= set(_IDENT.findall(facts)):
        return fallback
    return reply, "llm"
