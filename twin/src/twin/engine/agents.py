"""Per-car LLM agent: decides which place to drive to next.

Called only at decision points (spawn, and each time a car finishes
dwelling at a place) — never per-tick — so this scales to many concurrent
cars without hammering the API or blocking the physics loop. The caller is
expected to run this in a background asyncio task and not await it inline
in the tick loop.
"""
from __future__ import annotations

import json
import os
import random

MODEL = "openai/gpt-oss-20b"
MAX_PLACE_CHOICES = 12   # cap how many places we offer per decision, keeps the prompt small/fast

PERSONAS = [
    "a tired night-shift worker heading home to rest",
    "a parent juggling school pickup and errands",
    "a retiree who enjoys slow mornings at cafes",
    "a student rushing between classes and part-time work",
    "a delivery driver always looking for the next stop",
    "a fitness enthusiast who never skips the gym",
    "a small business owner running daily errands",
    "a freelancer who works from different cafes each day",
    "a new parent stocking up on groceries and supplies",
    "someone treating themselves to a nice meal out",
    "a commuter who values routine and predictability",
    "a social butterfly always meeting friends somewhere new",
]

_client = None


def _get_client():
    # the LLM libraries are optional (`--group llm`): the random traffic never gets here
    from dotenv import load_dotenv  # noqa: PLC0415
    from groq import AsyncGroq  # noqa: PLC0415

    load_dotenv()
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set")
        _client = AsyncGroq(api_key=api_key)
    return _client


def random_persona() -> str:
    return random.choice(PERSONAS)


DRIVE_TO_TOOL = {
    "type": "function",
    "function": {
        "name": "drive_to",
        "description": "Choose the destination place to drive to next.",
        "parameters": {
            "type": "object",
            "properties": {
                "place_id": {"type": "string", "description": "id of the chosen place"},
                "reason": {"type": "string", "description": "one short sentence explaining the choice"},
            },
            "required": ["place_id"],
        },
    },
}


def _build_prompt(persona: str, places: list[dict], current_place_name: str | None) -> list[dict]:
    system = (
        f"You are {persona}, driving around a city. "
        "Given a short list of nearby places, pick exactly one to drive to next using the drive_to tool. "
        "Stay in character with your persona when choosing, but keep it plausible and varied over time."
    )
    lines = [f"{p['id']} = {p['name']} ({p['category']})" for p in places]
    location_note = f"You are currently at/near {current_place_name}. " if current_place_name else ""
    user = f"{location_note}Nearby places you could drive to:\n" + "\n".join(lines) + "\n\nWhere do you go?"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def decide_next_place(
    persona: str,
    places: list[dict],
    current_place_name: str | None = None,
) -> tuple[str | None, str | None]:
    """Returns (chosen place id, reasoning text). Both None on any failure
    (caller should fall back to random); reasoning may be None even on
    success if the model didn't provide one."""
    if not places:
        return None, None

    sample = random.sample(places, min(len(places), MAX_PLACE_CHOICES))
    valid_ids = {p["id"] for p in sample}

    try:
        client = _get_client()
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=_build_prompt(persona, sample, current_place_name),
            tools=[DRIVE_TO_TOOL],
            tool_choice="required",
            timeout=8.0,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return None, None
        args = json.loads(msg.tool_calls[0].function.arguments)
        place_id = args.get("place_id")
        reason = args.get("reason")
        return (place_id if place_id in valid_ids else None), reason
    except Exception:
        return None, None
