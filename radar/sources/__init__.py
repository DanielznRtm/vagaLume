"""One module per source. Every module exposes:

    NAME: str                         short name shown in the report
    fetch(config: dict) -> SourceResult

and a pure `parse_*` function (no network) that the tests call with saved
sample responses from tests/fixtures/.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Opportunity


@dataclass
class SourceResult:
    """What a source hands back to the main loop."""

    items: list[Opportunity] = field(default_factory=list)
    # Problems that did not stop the whole source, e.g. one company's board
    # failed while the other 80 worked.
    errors: list[str] = field(default_factory=list)
    # How many boards / pages / queries we tried (for the health table).
    checked: int = 0
