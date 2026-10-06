# Opportunity Radar

A small Python bot that runs every day on GitHub Actions and collects **student
opportunities**: internships (summer and regular, Brazil and abroad), estágio,
research internships, fellowships, summer schools, and student programs at big
tech companies, AI labs and trading firms.

**The core rule: show everything, never decide for me.** Every student-level
posting found is kept. Nothing is dropped for eligibility, area or fit. Instead,
each posting gets **labels** (area, season, region) and **warnings** (such as
"US work auth?" or "PhD-level?"). When it is unclear whether a posting is for
students, it is still shown, with the warning `unsure if student role`.

Every day it updates:

- **The website** (`docs/`, served by GitHub Pages): one plain page with a
  search box, tabs (All, New, Closing in 14 days, Programs & schools, Applied,
  Hidden), a few filters and a table. See [The website](#the-website).
- `reports/latest.md`: the same list as a Markdown file you can read on
  GitHub. Order: deadlines in the next 14 days, then new items, then watched
  program pages, then everything else that is open, grouped by category.
- `data/radar.db`: an SQLite database with every posting ever seen and your
  status for each one.

---

## Sources

Each source is one module in `radar/sources/`. They all return the same record
(`radar/models.py`). If one source fails, the run goes on, and the failure shows
up in the **Source health** table at the top of the report.

Numbers from the run on 2026-10-06, after removing duplicates:

| Source | Module | How | Items |
|---|---|---|---|
| Greenhouse boards (99 companies, incl. Hudson River Trading) | `greenhouse.py` | public JSON API | 793 |
| Lever boards (10 companies) | `lever.py` | public JSON API | 107 |
| Ashby boards (49 companies) | `ashby.py` | public JSON API | 98 |
| GitHub lists (SimplifyJobs Summer 2027, Off-Season, New Grad; vanshb03 Summer 2027) | `github_lists.py` | parses README tables (HTML and Markdown) | 3,724 |
| Gupy (estágio in Brazil) | `gupy.py` | reads the JSON embedded in the search page | 97 |
| Program pages (25 pages) | `programs.py` | page-change watcher | 25 |
| Google Careers | `google.py` | reads the job data embedded in the results page | 63 |
| Amazon Jobs | `amazon.py` | JSON endpoint behind amazon.jobs search | 400 |
| NVIDIA (Workday) | `nvidia.py` | Workday JSON endpoint, "Intern" filter | 40 |
| Microsoft | `microsoft.py` | JSON endpoint behind its search page | 72 |
| D. E. Shaw | `nextjs_sites.py` | reads the JSON embedded in the page (Next.js) | 12 |
| DRW | `nextjs_sites.py` | reads the JSON embedded in the page (Next.js) | 23 |
| Meta | `meta.py` | **headless browser** (Playwright): opens the internship search and catches the job list the page downloads | 11 |

Total: **5,457 open items**, all 13 sources healthy.

**Scraping without a public API.** Most sites that have no official API still
load their jobs from somewhere: a JSON endpoint that the search page calls
(Microsoft, Amazon), or JSON embedded in the HTML (Gupy, Google, D. E. Shaw,
DRW). The bot reads those directly with plain HTTP, which is fast and simple.
Only Meta answers plain requests with an empty page, so `meta.py` opens it
in a headless Chromium (`radar/browser.py`) and reads the job list the page
fetches for itself. Program pages that are built by JavaScript can use the
same browser: add `render: true` in `programs.yaml`.

### Limits you should know about

- **Gupy** no longer has a public JSON API. Its search page holds only the
  **12 newest results per search term**, so the bot runs 17 searches (see
  `config/search.yaml`). Older estágio postings that drop off the first page are
  missed. Add more terms to cover more.
- **Google, Meta, Microsoft, D. E. Shaw, DRW** are scraped from their own
  websites. If one of them redesigns its site, that source will show as failed
  in the Sources table (the other sources keep working) and its parser needs a
  small update.
- **Microsoft** sometimes answers "429 Too Many Requests". The bot then waits
  15 s and 45 s before retrying, as the site asks.
- **Sites behind Cloudflare's bot check** (Citadel, MBZUAI, OpenAI Residency)
  stop even a full headless browser at a "security verification" page. Getting
  past it would mean disguising the browser or solving the challenge, which is
  defeating their anti-bot protection, so the radar doesn't do it. Where
  possible it reads the same postings from another source instead (see below).
- **New-grad roles** are included because you asked for the SimplifyJobs
  new-grad list. They carry the warning `new-grad role (after graduation)`.
- Postings that a source stops listing are marked closed. If a source is only
  partly healthy, closing waits until a posting hasn't been seen for 30 days.
- No LinkedIn scraping, by design.

### Check these by hand

| Site | What the radar still sees | Link |
|---|---|---|
| Citadel / Citadel Securities | their internships and new-grad roles from the SimplifyJobs lists | https://www.citadel.com/careers/students/ |
| MBZUAI UGRIP | nothing | https://mbzuai.ac.ae/ugrip/ |
| OpenAI Residency | residency roles when OpenAI posts them on its Ashby board (already read daily) | https://openai.com/residency/ |

Hudson River Trading used to be on this list. Its website blocks bots, but its
jobs live on Greenhouse under the board name `wehrtyou`, so it is now read
from the public API like any other company.

### Companies not on Greenhouse, Lever or Ashby

They stay commented out in `config/companies.yaml`:

- **Trading:** Two Sigma and SIG (watched as program pages), G-Research,
  Radix, Headlands. D. E. Shaw and DRW have their own scrapers now.
- **AI:** Google DeepMind (covered by the Google source and the Student
  Researcher page), Mistral AI, Hugging Face (uses Workable, which isn't
  supported).
- **Brazil:** iFood, Mercado Livre, PicPay, CloudWalk, Creditas, Hotmart,
  Olist, TOTVS, Tractian, Loggi. Several of them hire interns through Gupy, so
  the Gupy source may catch them.

---

## Labels

Labels come from keyword rules in `radar/labels.py`. All the keyword lists are
at the top of that file, so you can change them.

| Label | Values |
|---|---|
| area | `ML`, `SWE`, `research`, `data`, `quant`, `hardware`, `other` |
| season | `Dec–Feb` (Brazilian summer break), `Jul` (July break), `May–Aug` (northern summer), `year-round`, `unknown` |
| region | `Brazil`, `LatAm`, `US/Canada`, `Europe`, `Asia/ME` (includes Oceania), `remote`, `unknown`. A posting can have several. |
| warnings | `US work auth?`, `PhD-level?`, `grad-year limit?`, `unsure if student role`, `new-grad role (after graduation)` |
| calendar note | whether it fits UNESP's breaks or clashes with the semesters (Mar–Jul, Aug–Dec) |
| deadline | a date when the source or the text states one, otherwise `check page` |

**Optional Claude labelling.** If the secret `ANTHROPIC_API_KEY` is set, new
postings are also sent (title, location and description) to Claude Haiku 4.5,
the cheapest current model. It fills the labels and the deadline more
accurately. It can never remove a posting; if it thinks a posting isn't for
students, it only adds the `unsure if student role` warning. At most 150 new
postings are labelled per run (`RADAR_LLM_MAX_ITEMS` changes that). Without the
key, everything works the same using the keyword rules.

---

## The website

The site is one plain HTML file, `docs/index.html`. Each run rewrites
`docs/data.json` and the page shows it. The page has:

- **Search** over role, company and place.
- **Tabs**: All · New (found in the latest run) · Closing in 14 days ·
  Programs & schools · Applied · Hidden. Each tab shows its count.
- **Filters**: Area, Region, Season, Source, plus "Hide roles marked: US
  auth? / PhD? / grad year? / new grad / unsure". Nothing is hidden until you
  pick something.
- **Sort**: deadline first (default), newest first, or company A–Z.
- **Applied** and **Hide** buttons on each row. These are saved in your
  browser. Click again to undo.
- The **Sources** section at the bottom shows whether each source worked.

**Turn it on (one time):** in the repository go to *Settings → Pages*, set
*Source* to **Deploy from a branch**, pick branch **main** and folder
**/docs**, and save. A minute later the site is live at
**https://pedrocamargolince.github.io/opportunity-radar/**, and it updates
after every daily run. The repository is public, so the site is public too.

To try it on your computer: `python -m http.server -d docs` and open
http://localhost:8000.

### Statuses that follow you everywhere

The Applied/Hide buttons only remember things in one browser. For a status
that every device sees, add the posting's id to `config/status.yaml` (edit it
on github.com), for example:

```yaml
55047c2880ed6544: applied
3f9a1c2b7d4e5f60: ignored   # shows under "Hidden"
```

Statuses are `new`, `seen`, `applied` or `ignored`. The bot itself only
changes `new` to `seen` on the next run. Locally you can also run
`python -m radar status <id> applied`.

---

## How to add things

**A company.** Open one of its job postings and look at the URL:

| URL looks like | Put it under | slug |
|---|---|---|
| `boards.greenhouse.io/anthropic/...` or `job-boards.greenhouse.io/anthropic/...` | `greenhouse:` | `anthropic` |
| `jobs.lever.co/palantir/...` | `lever:` | `palantir` |
| `jobs.ashbyhq.com/openai/...` | `ashby:` | `openai` |

Then add `- {slug: anthropic, name: Anthropic}` to `config/companies.yaml` and
run `python -m radar check-config` to confirm that it returns jobs.

**A program page.** Add an entry to `config/programs.yaml`:

```yaml
  - name: Some Summer School
    org: Some University
    url: https://example.org/summer-school
    area: ML              # optional; otherwise guessed from the page
    season: Jul           # optional
    regions: [Europe]     # optional
    notes: "deadline usually in March"
```

Run `python -m radar check-config`. If the page shows fewer than 200
characters, it is probably built by JavaScript: add `render: true` and it will
be opened in the headless browser instead.

**More Gupy searches, GitHub lists, Google/Amazon queries:** edit
`config/search.yaml`.

---

## Setting it up on GitHub

1. **Merge to the default branch.** GitHub runs scheduled workflows only on the
   default branch (`main`).
2. **Allow the workflow to push.** Go to *Settings → Actions → General →
   Workflow permissions* and pick **Read and write permissions**. The workflow
   commits `data/radar.db` and `reports/`.
3. **Turn on the website:** *Settings → Pages → Deploy from a branch → main,
   /docs*.
4. The schedule is daily at **09:00 Brasília (12:00 UTC)**. To run it now, open
   *Actions → Opportunity Radar → Run workflow*.

### Secrets (all optional)

Add them under *Settings → Secrets and variables → Actions → New repository
secret*. Anything you leave out is skipped without errors.

| Secret | What for |
|---|---|
| `ANTHROPIC_API_KEY` | better labels from Claude (see above). Get a key at console.anthropic.com. |
| `TELEGRAM_BOT_TOKEN` | Telegram digest. Create a bot by talking to **@BotFather** (`/newbot`); it gives you the token. |
| `TELEGRAM_CHAT_ID` | your chat id. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `message.chat.id`. |
| `SMTP_HOST`, `SMTP_PORT` | email server, e.g. `smtp.gmail.com` and `587` |
| `SMTP_USER`, `SMTP_PASSWORD` | login. For Gmail, use an **App password** (Google Account → Security → 2-Step Verification → App passwords), not your normal password. |
| `EMAIL_TO` | where to send the digest |
| `EMAIL_FROM` | optional sender address (defaults to `SMTP_USER`) |

You can also set the repository **variable** `RADAR_REPORT_URL` to the site
address (https://pedrocamargolince.github.io/opportunity-radar/) and the digest
will link to it.

---

## Running it locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium   # headless browser, only needed for Meta

python -m radar                      # full run (about 5 minutes)
python -m radar --only gupy,programs # just some sources
python -m radar --no-notify          # don't send Telegram/email
python -m radar check-config         # verify every slug and program URL
python -m pytest -q                  # tests (offline, use saved samples)
```

---

## How the code is organised

```
radar/
  main.py          the daily run, step by step (start reading here)
  models.py        the Opportunity record every source returns
  http.py          polite HTTP: user-agent, timeouts, small delays, retries
  browser.py       headless Chromium, only for sites that need JavaScript
  labels.py        keyword rules for area / season / region / warnings
  llm.py           optional Claude labelling (only with ANTHROPIC_API_KEY)
  db.py            SQLite storage, dedupe by id (hash of the URL)
  report.py        writes reports/latest.md
  site.py          writes docs/data.json for the website
  notify.py        optional Telegram / email digest
  textutil.py      HTML to text, date parsing, deadline finding
  sources/         one module per source; each has a pure parse() function
docs/              the website: index.html (fixed) + data.json (updated daily)
config/            companies.yaml, programs.yaml, search.yaml, status.yaml
tests/             pytest tests; tests/fixtures holds saved real responses
```

A run does four things, in this order: **collect** from each source (failures
are caught per source), **label** with rules (plus Claude if a key is set),
**store** in SQLite (dedupe by URL hash, keep your status), and **publish**
(website data, Markdown report, notifications).

## Notes

- **Polite scraping.** The bot sends a user-agent that says what it is and
  links here, waits 0.6 s before each request, uses 25 s timeouts, retries
  once (longer pauses after a 429), and does not get around bot protection.
  A full run makes about 240 requests and opens 2 pages in the browser.
- **Repository size.** `data/radar.db` (2.8 MB) and `docs/data.json` (2.5 MB)
  are committed every day.
  Git stores each version, so the repository grows over time. If it gets too
  big, you can delete old history, or store the database as a workflow
  artifact instead.
