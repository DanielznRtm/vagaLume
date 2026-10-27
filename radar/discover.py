"""Find new companies to read, every day, without anyone adding them by hand.

Many companies, Brazilian startups among them, post their jobs on Ashby, Greenhouse or Lever, which
vagaLume already reads: it only needs to know the company's board (Enter, an AI startup in São
Paulo, is jobs.ashbyhq.com/enter-ai). Nobody publishes the list of boards, but Common Crawl, a free
public archive of the web, has seen most of them: its index lists every jobs.ashbyhq.com/<company>
page it crawled. Each day:

1. read the board names from the index of the last CRAWLS crawls (a few small slices of it, not the
   whole index: it is sorted by address, so a binary search finds the jobs.ashbyhq.com part);
2. ask boards for their jobs through the same public APIs the sources use: the new ones first, then
   the ones last asked over RECHECK_DAYS ago (a week for those with jobs in Brazil), CHECKS_PER_RUN
   at most;
3. keep the boards with a job in Brazil in config/discovered.yaml, which load_config adds to the
   companies of config/companies.yaml. A board with no job in Brazil any more, or gone, drops out.

data/discovery.jsonl remembers what each board had the last time it was asked.

    python -m radar discover          # what the daily workflow runs
"""

from __future__ import annotations

import gzip
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import requests
import yaml

from .config import CONFIG_DIR, ROOT, _load
from .http import get_json, get_range, get_text
from .labels import classify_regions, is_student_candidate

log = logging.getLogger(__name__)

CC_DATA = "https://data.commoncrawl.org/"
CRAWLS = 6  # about half a year: one crawl misses a board that another one saw (Enter: 3 of the last 6)
CHECKS_PER_RUN = 1500
RECHECK_DAYS = 30
RECHECK_BRAZIL_DAYS = 7
STATE = ROOT / "data" / "discovery.jsonl"
OUTPUT = CONFIG_DIR / "discovered.yaml"
SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
NOT_SLUGS = {"embed", "api", "static", "assets", "favicon.ico", "robots.txt", "sitemap.xml", "jobs", "job", "b", "meeting"}


def _places_ashby(job: dict[str, Any]) -> str:
    country = ((job.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or ""
    extra = [str(p.get("location") or "") for p in job.get("secondaryLocations") or [] if isinstance(p, dict)]
    return " / ".join(p for p in [", ".join(p for p in (str(job.get("location") or ""), country) if p), *extra] if p)


def _places_greenhouse(job: dict[str, Any]) -> str:
    return str((job.get("location") or {}).get("name") or "")


def _places_lever(job: dict[str, Any]) -> str:
    categories = job.get("categories") or {}
    places = categories.get("allLocations") or [categories.get("location") or ""]
    country = {"BR": "Brazil"}.get(str(job.get("country") or ""), "")
    return " / ".join(str(p) for p in [*places, country] if p)


def _title_name(url: str) -> str:
    """ "<title>Enter Jobs</title>" -> "Enter" (Ashby and Lever boards say the company only there)."""
    match = re.search(r"<title>([^<]+)</title>", get_text(url))
    return re.sub(r"\s+(?:Jobs|Careers)$", "", match[1].strip()) if match else ""


@dataclass(frozen=True)
class Platform:
    prefixes: tuple[str, ...]  # the boards' addresses in Common Crawl's index (SURT form: host reversed)
    jobs: str  # API with every job of a board
    places: Callable[[dict[str, Any]], str]
    name: Callable[[str], str]  # slug -> company name

    def job_list(self, slug: str) -> list[dict[str, Any]]:
        data = get_json(self.jobs.format(slug=slug))
        return data if isinstance(data, list) else data.get("jobs") or []


PLATFORMS = {
    "ashby": Platform(("com,ashbyhq,jobs)/",), "https://api.ashbyhq.com/posting-api/job-board/{slug}", _places_ashby,
                      lambda slug: _title_name(f"https://jobs.ashbyhq.com/{slug}")),
    "greenhouse": Platform(("io,greenhouse,boards)/", "io,greenhouse,job-boards)/"),
                           "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", _places_greenhouse,
                           lambda slug: str(get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}").get("name") or "")),
    "lever": Platform(("co,lever,jobs)/",), "https://api.lever.co/v0/postings/{slug}?mode=json", _places_lever,
                      lambda slug: _title_name(f"https://jobs.lever.co/{slug}")),
}


# --- 1. Board names from Common Crawl's index --------------------------------------------------
def latest_crawls(count: int = CRAWLS) -> list[str]:
    ids = set(re.findall(r"CC-MAIN-\d{4}-\d{2}", get_text(CC_DATA + "crawl-data/index.html")))
    return sorted(ids, reverse=True)[:count]


def slug_from_key(key: str, prefix: str) -> str:
    """ "com,ashbyhq,jobs)/enter-ai/7b44..." -> "enter-ai"; Greenhouse's embed links name the board in "for="."""
    path = key[len(prefix):]
    slug = path.split("/")[0].split("?")[0].lower()
    if slug == "embed":
        slug = (re.search(r"[?&]for=([\w.-]+)", path) or [None, ""])[1].lower()
    return slug if SLUG.match(slug) and slug not in NOT_SLUGS else ""


def index_slugs(crawl: str, prefix: str) -> set[str]:
    """Every board under `prefix` in one crawl's index. cluster.idx has one line per block of 3,000
    index lines ("key timestamp<TAB>file<TAB>offset<TAB>length<TAB>n"), sorted by key: find the blocks
    that can hold the prefix with a binary search over byte ranges, then read just those blocks."""
    base = f"{CC_DATA}cc-index/collections/{crawl}/indexes/"
    size = int(requests.head(base + "cluster.idx", timeout=60).headers["content-length"])

    def line_after(position: int) -> str:
        chunk = get_range(base + "cluster.idx", position, min(size - 1, position + 8192)).decode("utf-8", "replace")
        return (chunk.split("\n", 1)[1] if position else chunk).split("\n", 1)[0]

    low, high = 0, size
    while high - low > 65536:
        middle = (low + high) // 2
        low, high = (middle, high) if line_after(middle).split(" ")[0] < prefix else (low, middle)
    blocks: list[list[str]] = []
    previous: list[str] | None = None
    position = low
    while True:
        chunk = get_range(base + "cluster.idx", position, min(size - 1, position + 1_000_000)).decode("utf-8", "replace")
        lines = chunk.split("\n")
        start = 1 if position else 0
        finished = position + len(chunk.encode()) >= size
        for line in lines[start:-1]:
            key, parts = line.split(" ")[0], line.split("\t")
            if key >= prefix and not blocks and previous:
                blocks.append(previous)  # the block before the first match can hold the first boards
            if key.startswith(prefix):
                blocks.append(parts)
            elif key > prefix:
                blocks.append(parts)
                finished = True
                break
            previous = parts
        if finished:
            break
        position += len(chunk.encode()) - len(lines[-1].encode())
    slugs: set[str] = set()
    for parts in blocks:
        offset, length = int(parts[2]), int(parts[3])
        for line in gzip.decompress(get_range(base + parts[1], offset, offset + length - 1)).decode("utf-8", "replace").splitlines():
            if line.startswith(prefix) and (slug := slug_from_key(line.split(" ")[0], prefix)):
                slugs.add(slug)
    return slugs


def candidates(crawls: list[str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {name: set() for name in PLATFORMS}
    for crawl in crawls:
        for name, platform in PLATFORMS.items():
            for prefix in platform.prefixes:
                try:
                    found[name] |= index_slugs(crawl, prefix)
                except Exception as error:  # noqa: BLE001 - one crawl's index must not stop the others
                    log.warning("Common Crawl %s %s: %s", crawl, prefix, error)
    return found


# --- 2. What each board has ---------------------------------------------------------------------
def check(platform_name: str, slug: str, today: str) -> dict[str, Any]:
    """How many of the board's jobs are in Brazil, and how many of those look like student roles.
    A board that is gone (404) is remembered as gone."""
    platform = PLATFORMS[platform_name]
    record: dict[str, Any] = {"platform": platform_name, "slug": slug, "checked": today}
    try:
        jobs = platform.job_list(slug)
    except requests.HTTPError as error:
        if error.response is not None and error.response.status_code in (404, 410):
            return record | {"gone": True}
        raise
    brazil = [job for job in jobs if "Brazil" in classify_regions(platform.places(job), False)]
    record |= {"jobs": len(jobs), "brazil": len(brazil),
               "students": sum(1 for job in brazil if is_student_candidate(str(job.get("title") or job.get("text") or "")))}
    if brazil:
        try:
            record["name"] = platform.name(slug)
        except Exception:  # noqa: BLE001 - the slug will do
            pass
    return record


def due(found: dict[str, set[str]], state: dict[tuple[str, str], dict[str, Any]], configured: dict[str, set[str]],
        today: date, limit: int = CHECKS_PER_RUN) -> list[tuple[str, str]]:
    """Boards to ask today: never asked first, then the oldest answers (a week for boards with jobs in
    Brazil, RECHECK_DAYS for the others). Boards already in companies.yaml are read every day anyway."""
    def age(record: dict[str, Any]) -> int:
        return (today - date.fromisoformat(record["checked"])).days

    known = {key for key in state}
    new = sorted((p, s) for p, slugs in found.items() for s in slugs if (p, s) not in known and s not in configured.get(p, set()))
    old = sorted(((p, s) for (p, s), r in state.items() if s not in configured.get(p, set())
                  and age(r) >= (RECHECK_BRAZIL_DAYS if r.get("brazil") else RECHECK_DAYS)),
                 key=lambda key: state[key]["checked"])
    brazil_first = sorted(old, key=lambda key: not state[key].get("brazil"))
    return (new + brazil_first)[:limit]


# --- 3. State and output ------------------------------------------------------------------------
def load_state(path: Path = STATE) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    records = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return {(r["platform"], r["slug"]): r for r in records}


def save_state(state: dict[tuple[str, str], dict[str, Any]], path: Path = STATE) -> None:
    lines = [json.dumps(state[key], ensure_ascii=False, sort_keys=True) for key in sorted(state)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_discovered(state: dict[tuple[str, str], dict[str, Any]], configured: dict[str, set[str]], path: Path = OUTPUT) -> int:
    """config/discovered.yaml: the boards with jobs in Brazil, most first. Returns how many."""
    lines = ["# Written every day by `python -m radar discover` (radar/discover.py): companies on Ashby, Greenhouse",
             "# and Lever with jobs in Brazil, found through Common Crawl. Don't edit: to keep a company for good,",
             "# add it to companies.yaml (it then leaves this list); to leave one out, add it to ignored_boards there.", ""]
    count = 0
    for platform in PLATFORMS:
        rows = sorted((r for (p, s), r in state.items() if p == platform and r.get("brazil") and not r.get("gone")
                       and s not in configured.get(platform, set())),
                      key=lambda r: (-r["brazil"], r["slug"]))
        lines.append(f"{platform}:" + ("" if rows else " []"))
        for r in rows:
            entry = yaml.safe_dump({"slug": r["slug"], "name": r.get("name") or r["slug"]}, default_flow_style=True,
                                   allow_unicode=True, width=1000).strip()
            lines.append(f"  - {entry}  # {r['brazil']} jobs in Brazil, {r.get('students', 0)} for students ({r['checked']})")
        count += len(rows)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return count


def configured_boards() -> dict[str, set[str]]:
    """Boards in companies.yaml, and the ones it says to leave out (ignored_boards: {ashby: [slug]})."""
    companies = _load("companies.yaml") or {}
    ignored = companies.get("ignored_boards") or {}
    return {p: {str(c["slug"]).lower() for c in companies.get(p) or []} | {str(s).lower() for s in ignored.get(p) or []}
            for p in PLATFORMS}


def run(today: date | None = None, limit: int = CHECKS_PER_RUN, workers: int = 8) -> int:
    """The daily discovery. Returns how many boards config/discovered.yaml lists."""
    today = today or date.today()
    state = load_state()
    configured = configured_boards()
    found = candidates(latest_crawls())
    log.info("Common Crawl: %s boards", {p: len(s) for p, s in found.items()})
    todo = due(found, state, configured, today, limit)

    def ask(key: tuple[str, str]) -> dict[str, Any] | None:
        try:
            return check(key[0], key[1], today.isoformat())
        except Exception as error:  # noqa: BLE001 - asked again another day
            log.info("Board %s/%s: %s", key[0], key[1], error)
            return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, record in zip(todo, pool.map(ask, todo)):
            if record:
                state[key] = record
    save_state(state)
    count = write_discovered(state, configured)
    log.info("Discovery: asked %d boards, %d with jobs in Brazil", len(todo), count)
    return count

