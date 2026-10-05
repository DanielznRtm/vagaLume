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

Every day it writes:

- `reports/latest.md`: readable on GitHub. Order: deadlines in the next 14 days,
  then new items, then watched program pages, then everything else that is
  open, grouped by category.
- `reports/index.html`: the same data as a page with filters. Every filter
  starts ticked, so nothing is hidden until you choose.
- `data/radar.db`: an SQLite database with every posting ever seen and your
  status for each one.

---

## Sources

Each source is one module in `radar/sources/`. They all return the same record
(`radar/models.py`). If one source fails, the run goes on, and the failure shows
up in the **Source health** table at the top of the report.

These are the numbers from the first real run (2026-10-05), after removing
duplicates:

| Source | Module | How | Status | Items |
|---|---|---|---|---|
| Greenhouse boards (98 companies) | `greenhouse.py` | public JSON API | ✅ working | 785 |
| Lever boards (10 companies) | `lever.py` | public JSON API | ✅ working | 107 |
| Ashby boards (49 companies) | `ashby.py` | public JSON API | ✅ working | 98 |
| GitHub lists (SimplifyJobs Summer 2027, Off-Season, New Grad; vanshb03 Summer 2027) | `github_lists.py` | parses README tables (HTML and Markdown) | ✅ working | 3,731 |
| Gupy (estágio in Brazil) | `gupy.py` | reads the JSON embedded in the search page | ✅ working, see limits | 97 |
| Program pages (24 pages) | `programs.py` | page-change watcher | ✅ working | 24 |
| Google Careers | `google.py` | reads the job data embedded in the results page | ✅ working (fragile) | 63 |
| Amazon Jobs | `amazon.py` | JSON endpoint behind amazon.jobs search | ✅ working | 400 |
| NVIDIA (Workday) | `nvidia.py` | Workday JSON endpoint, "Intern" filter | ✅ working | 40 |
| Microsoft | - | its search API answered **429 Too Many Requests** every time | ⚠️ watched page instead | - |
| Meta | - | no public API, and the pages are built by JavaScript | ❌ not covered, check by hand | - |

Total on the first run: **5,345 open items**.

### Limits you should know about

- **Gupy** no longer has a public JSON API. Its search page holds only the
  **12 newest results per search term**, so the bot runs 17 searches (see
  `config/search.yaml`). Older estágio postings that drop off the first page are
  missed. Add more terms to cover more.
- **Google** has no API. The parser reads a data blob inside the page by
  position. If Google changes its page, this source will show as failed in the
  report. The Google student pages in `programs.yaml` act as a backup.
- **Microsoft**'s job search API (`apply.careers.microsoft.com`) refused every
  request with HTTP 429, so Microsoft is covered only as a watched page
  (`careers.microsoft.com/v2/global/en/students`), plus whatever the GitHub
  lists pick up.
- **Meta**'s career site is built entirely by JavaScript and has no public API.
  Neither a search nor a page watch works. Meta internships still show up
  through the SimplifyJobs lists.
- **New-grad roles** are included because you asked for the SimplifyJobs
  new-grad list. They carry the warning `new-grad role (after graduation)`.
- Postings that a source stops listing are marked closed. If a source is only
  partly healthy, closing waits until a posting hasn't been seen for 30 days.
- No LinkedIn scraping, by design.

### Companies that could not be added

These were checked on 2026-10-05 and are not on Greenhouse, Lever or Ashby, or
their board could not be found. They stay commented out in
`config/companies.yaml`:

- **Trading:** Hudson River Trading, Citadel, Citadel Securities, Two Sigma,
  D. E. Shaw, Susquehanna (SIG), DRW, G-Research, Radix, Headlands. Two Sigma
  and SIG are watched as pages instead. HRT and Citadel block bots (HTTP 403),
  and D. E. Shaw and DRW pages are JavaScript-only, so check those by hand.
- **AI:** Google DeepMind (covered by the Google source and the Student
  Researcher page), Mistral AI, Hugging Face (uses Workable, which isn't
  supported).
- **Brazil:** iFood, Mercado Livre, PicPay, CloudWalk, Creditas, Hotmart,
  Olist, TOTVS, Tractian, Loggi. Several of them hire interns through Gupy, so
  the Gupy source may catch them.

### Program pages that could not be watched

Also commented out in `config/programs.yaml`:

| Page | Why |
|---|---|
| MBZUAI UGRIP | HTTP 403 (bot protection) |
| OpenAI Residency | HTTP 403 (bot protection) |
| Hudson River Trading campus (Explore/Inside HRT) | HTTP 403 |
| Citadel students | HTTP 403 |
| Google STEP | page is built by JavaScript. STEP roles are found by the Google source instead (query `STEP`). |
| Meta university programs | page is built by JavaScript |
| D. E. Shaw students | page is built by JavaScript |
| DRW campus listings | job list is loaded by JavaScript |

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

## Your status for each posting

Every posting has a status: `new`, `seen`, `applied` or `ignored`. The bot only
ever changes `new` to `seen` (on the next run). To set your own status:

1. Copy the posting's id (the small grey code in the report, such as `55047c2880ed6544`).
2. Add a line to `config/status.yaml`, for example `55047c2880ed6544: applied`.
   You can do this on github.com with the pencil icon.

The next run applies it. `ignored` items move to an "Ignored by you" section at
the bottom of the report. You can also do this locally:
`python -m radar status 55047c2880ed6544 applied`.

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
characters, it is probably built by JavaScript and can't be watched.

**More Gupy searches, GitHub lists, Google/Amazon queries:** edit
`config/search.yaml`.

---

## Setting it up on GitHub

1. **Merge to the default branch.** GitHub runs scheduled workflows only on the
   default branch (`main`).
2. **Allow the workflow to push.** Go to *Settings → Actions → General →
   Workflow permissions* and pick **Read and write permissions**. The workflow
   commits `data/radar.db` and `reports/`.
3. The schedule is daily at **09:00 Brasília (12:00 UTC)**. To run it now, open
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

You can also set the repository **variable** `RADAR_REPORT_URL`, for example a
GitHub Pages link to `reports/index.html`, and the digest will include it.

### Reading the HTML report

GitHub shows `reports/latest.md` nicely but shows `index.html` only as code.
You have three options:

- Download it (*Raw → Save as*) and open it in your browser.
- Clone the repo and open `reports/index.html`.
- Turn on GitHub Pages (*Settings → Pages → Deploy from branch → main / root*)
  and open `https://<user>.github.io/opportunity-radar/reports/`. On a free
  account, Pages needs the repository to be public, and that makes your list
  public too.

---

## Running it locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

python -m radar                      # full run (about 4 minutes)
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
  http.py          polite HTTP: user-agent, timeouts, small delays, one retry
  labels.py        keyword rules for area / season / region / warnings
  llm.py           optional Claude labelling (only with ANTHROPIC_API_KEY)
  db.py            SQLite storage, dedupe by id (hash of the URL)
  report.py        writes latest.md and index.html
  notify.py        optional Telegram / email digest
  textutil.py      HTML to text, date parsing, deadline finding
  sources/         one module per source; each has a pure parse() function
config/            companies.yaml, programs.yaml, search.yaml, status.yaml
tests/             pytest tests; tests/fixtures holds saved real responses
```

A run does four things, in this order: **collect** from each source (failures
are caught per source), **label** with rules (plus Claude if a key is set),
**store** in SQLite (dedupe by URL hash, keep your status), and **report**
(Markdown, HTML, notifications).

## Notes

- **Polite scraping.** The bot sends a user-agent that says what it is and
  links here, waits 0.6 s before each request, uses 25 s timeouts, and retries
  only once. A full run makes about 220 requests.
- **Database size.** `data/radar.db` is about 2.7 MB and is committed every day.
  Git stores each version, so the repository grows over time. If it gets too
  big, you can delete old history, or store the database as a workflow
  artifact instead.
