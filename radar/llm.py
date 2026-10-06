"""Optional: let a cheap Claude model refine the labels.

Only runs when the ANTHROPIC_API_KEY environment variable is set. Without
it the bot uses the keyword rules in labels.py and works exactly the same.

We call the Messages API with plain `requests` (no extra SDK dependency)
and ask for JSON that matches a fixed schema ("structured outputs"), so the
answer is always machine-readable.

The model only *labels*. It can never remove a posting: if it thinks a
posting is not for students, we add the "unsure if student role" warning.
"""

from __future__ import annotations

import json
import logging
import os
import re

import requests

from .labels import W_UNSURE, calendar_note
from .models import NO_DEADLINE, Opportunity

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("RADAR_CLAUDE_MODEL", "claude-haiku-4-5")  # cheapest current model
MAX_ITEMS_PER_RUN = int(os.environ.get("RADAR_LLM_MAX_ITEMS", "150"))
MAX_DESCRIPTION_CHARS = 4000

AREAS = ["ML", "SWE", "research", "data", "quant", "hardware", "other"]
SEASONS = ["Dec–Feb", "Jul", "May–Aug", "year-round", "unknown"]
REGIONS = ["Brazil", "LatAm", "US/Canada", "Europe", "Asia/ME", "remote", "unknown"]
WARNINGS = ["US work auth?", "PhD-level?", "grad-year limit?"]

# JSON schema the answer must follow.
SCHEMA = {
    "type": "object",
    "properties": {
        "area": {"type": "string", "enum": AREAS},
        "season": {"type": "string", "enum": SEASONS},
        "regions": {"type": "array", "items": {"type": "string", "enum": REGIONS}},
        "warnings": {"type": "array", "items": {"type": "string", "enum": WARNINGS}},
        "deadline": {"type": "string", "description": "YYYY-MM-DD, or empty if not stated"},
        "pay": {"type": "string", "description": "short pay label like '$45/hr' or 'R$1,800/mo', or empty"},
        "student_role": {"type": "string", "enum": ["yes", "no", "unsure"]},
    },
    "required": ["area", "season", "regions", "warnings", "deadline", "pay", "student_role"],
    "additionalProperties": False,
}

INSTRUCTIONS = """You label job and program postings for a Brazilian undergraduate \
(Control and Automation Engineering, graduating 2027-2028) who does ML research.
Return labels only; never judge whether they should apply.

- area: the main field of the role.
- season: when the work happens. "Dec–Feb" = southern summer break (Brazilian "verão"), \
"Jul" = July break, "May–Aug" = northern summer internship, "year-round" = during the \
academic year (fall/spring/co-op/regular estágio), "unknown" if not stated.
- regions: every region where the role can be done; add "remote" if remote is allowed.
- warnings: "US work auth?" if it is in the US/Canada or mentions work authorization, \
citizenship, sponsorship or clearance; "PhD-level?" if it targets PhD/advanced-degree \
students; "grad-year limit?" if it restricts graduation year or year of study.
- deadline: the application deadline if the text states one, else "".
- pay: the pay or stipend if stated, as a short label like "$45/hr", "€1,800/mo" or "R$1,800/mo", else "".
- student_role: "yes" if aimed at students, "no" if clearly a regular job, else "unsure"."""


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _ask_claude(opp: Opportunity, api_key: str) -> dict[str, object]:
    posting = (
        f"Title: {opp.title}\nOrganization: {opp.org}\nLocation: {opp.location}\n"
        f"Remote: {opp.remote}\nDescription:\n{opp.description[:MAX_DESCRIPTION_CHARS]}"
    )
    response = requests.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 400,
            "system": INSTRUCTIONS,
            "messages": [{"role": "user", "content": posting}],
            "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
        },
        timeout=60,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("stop_reason") == "refusal":
        raise ValueError("model declined to label this posting")
    text = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text")
    return json.loads(text)


def _merge(opp: Opportunity, answer: dict[str, object]) -> None:
    """Combine Claude's labels with the rule-based ones (warnings are unioned)."""
    if not opp.preset.get("area"):
        opp.area = str(answer["area"])
    if not opp.preset.get("season"):
        opp.season = str(answer["season"])
    if not opp.preset.get("regions") and answer["regions"]:
        opp.regions = list(dict.fromkeys(answer["regions"]))  # type: ignore[arg-type]
    warnings = list(opp.warnings)
    for warning in answer["warnings"]:  # type: ignore[union-attr]
        if warning not in warnings:
            warnings.append(str(warning))
    if answer["student_role"] in ("no", "unsure") and W_UNSURE not in warnings and "new-grad" not in opp.hints:
        warnings.append(W_UNSURE)
    opp.warnings = warnings
    deadline = str(answer.get("deadline") or "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", deadline) and opp.deadline == NO_DEADLINE:
        opp.deadline = deadline
    if not opp.pay and answer.get("pay"):
        opp.pay = str(answer["pay"])[:40]
    opp.calendar_note = calendar_note(opp.season)
    opp.labeled_by = "claude"


def refine_labels(opportunities: list[Opportunity]) -> int:
    """Ask Claude to label up to MAX_ITEMS_PER_RUN postings. Returns how many succeeded.

    Pass only *new* postings here to keep the cost low. Any error just
    leaves the keyword labels in place.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return 0
    done = 0
    for opp in opportunities[:MAX_ITEMS_PER_RUN]:
        try:
            _merge(opp, _ask_claude(opp, api_key))
            done += 1
        except Exception as error:  # noqa: BLE001 - never let labelling break the run
            log.warning("Claude labelling failed for %s: %s", opp.url, error)
    if len(opportunities) > MAX_ITEMS_PER_RUN:
        log.info("Claude labelled the first %d new items; the rest keep keyword labels", MAX_ITEMS_PER_RUN)
    return done
