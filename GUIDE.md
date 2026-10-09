# vagaLume: the full guide

This is the detailed manual: how every source works, what each label means,
how to add companies and programs, and how to run your own copy. For the short
tour, see the [README](README.md) (in Portuguese; [English version](README.en.md)). The website is at
**https://pedrocamargolince.github.io/vagaLume/**.

vagaLume is a small Python bot that runs every day on GitHub Actions and collects **student
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
- `data/opportunities.jsonl` and `data/page_hashes.jsonl`: the database as
  text, one posting per line, with every posting ever seen and your status for
  each one. Each run rebuilds a working SQLite file (`data/radar.db`, not
  committed) from them and writes them back at the end.

---

## Sources

Each source is one module in `radar/sources/`. They all return the same record
(`radar/models.py`). If one source fails, the run goes on, and the failure shows
up in the **Source health** table at the top of the report.

Numbers from the run on 2026-10-09, after removing duplicates:

| Source | Module | How | Items |
|---|---|---|---|
| Greenhouse boards (101 companies, incl. Hudson River Trading and AB InBev) | `greenhouse.py` | public JSON API | 810 |
| Lever boards (13 companies) | `lever.py` | public JSON API | 107 |
| Ashby boards (49 companies) | `ashby.py` | public JSON API | 98 |
| GitHub lists (SimplifyJobs Summer 2027, Off-Season, New Grad; vanshb03 Summer 2027) | `github_lists.py` | parses README tables (HTML and Markdown) | 3,898 |
| Gupy (estágio, estágio de férias and trainee in Brazil) | `gupy.py` | the portal's JSON search API, filtered by job type, 100 per page | 2,665 |
| Program pages (42 pages, 17 of them Brazilian) | `programs.py` | page-change watcher | 42 |
| Google Careers | `google.py` | reads the job data embedded in the results page | 90 |
| Amazon Jobs | `amazon.py` | JSON endpoint behind amazon.jobs search | 431 |
| NVIDIA (Workday) | `nvidia.py` | Workday JSON endpoint, "Intern" filter | 40 |
| Microsoft | `microsoft.py` | JSON endpoint behind its search page | 82 |
| D. E. Shaw | `nextjs_sites.py` | reads the JSON embedded in the page (Next.js) | 14 |
| DRW | `nextjs_sites.py` | reads the JSON embedded in the page (Next.js) | 27 |
| Meta | `meta.py` | **headless browser** (Playwright): opens the internship search and catches the job list the page downloads | 11 |
| **Brazil:** CIEE (graduação estágio) | `ciee.py` | the public JSON API behind portal.ciee.org.br, 1,000 per page | 2,223 |
| **Brazil:** Super Estágios (Superior level) | `superestagios.py` | one form POST that returns every active vacancy | 4,723 |
| **Brazil:** Sólides Vagas (estágio, last 60 days) | `solides.py` | the JSON route behind the search page, 20 per page | 972 |
| **Brazil:** IEL (estágio from the industry federations, last 60 days) | `iel.py` | public Liferay API | 826 |
| **Brazil:** Cia de Talentos (open estágio and trainee programs) | `ciadetalentos.py` | the public request the vacancy site makes before login | 10 |
| **Brazil:** FAPESP Oportunidades (IC, master's and doctoral grants) | `fapesp.py` | parses the static list page | 28 |
| **Brazil:** SmartRecruiters (Bosch, Syngenta, Louis Dreyfus, Aumovio, Continental, Serasa) | `smartrecruiters.py` | public API, Brazil only | 92 |
| **Brazil:** Workday (Santander, P&G, Citi, Mondelēz, Accenture, Hitachi and 13 more) | `workday.py` | Workday JSON endpoint with the Brazil and intern/apprentice filters | 70 |

Total: **17,038 open items, 11,688 of them in Brazil**, from 21 sources. (Meta, about 15 items, failed in this test run only because of the test machine's browser.)

**Scraping without a public API.** Most sites that have no official API still
load their jobs from somewhere: a JSON endpoint that the search page calls
(Microsoft, Amazon, Gupy, CIEE, Sólides), or JSON embedded in the HTML (Google,
D. E. Shaw, DRW). The bot reads those directly with plain HTTP, which is fast and simple.
Only Meta answers plain requests with an empty page, so `meta.py` opens it
in a headless Chromium (`radar/browser.py`) and reads the job list the page
fetches for itself. Program pages that are built by JavaScript can use the
same browser: add `render: true` in `programs.yaml`.

### Limits you should know about

- **Gupy, CIEE, Sólides, Super Estágios, IEL and Cia de Talentos** are read
  through the same JSON requests their own websites make. They are not
  official APIs, so a redesign can break one; it then shows as failed in the
  Sources table and the others keep working.
- **CIEE and Super Estágios vacancies have no job title.** vagaLume writes one
  from the professional area or the accepted courses ("Estágio em
  Informática"), and Super Estágios hides the company of about a third of its
  vacancies ("Empresa confidencial").
- **Sólides and IEL** keep old postings online, so only the last 60 days are
  read.
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
- **Brazil:** iFood, Mercado Livre, PicPay, Creditas, Hotmart, Olist, TOTVS,
  Loggi. Most Brazilian companies hire interns through Gupy, which the Gupy
  source reads in full (every internship, summer and trainee posting).
  CloudWalk and Tractian are real Lever boards that were empty in October 2026.

### Brazilian job sites we don't read, and why

Checked in October 2026. vagaLume only reads sites that allow it and never
gets around a block.

| Site | Why not |
|---|---|
| Catho | answers bots with HTTP 403 |
| Indeed, Glassdoor | Cloudflare bot check |
| InfoJobs | its terms forbid robots and crawlers |
| Vagas.com.br | robots.txt allows it, but its terms forbid copying content without authorization (asking them is an option) |
| Nube | the vacancy search needs a login (many Nube vacancies are also on Gupy) |
| Companhia de Estágios | the vacancy board needs a login; its open programs page is watched in `programs.yaml` |
| estagiarios.com | Cloudflare block |
| Coodesh | its API's robots.txt disallows all bots |
| LinkedIn | never |

Possible later, with care (allowed by robots.txt, few pages a day):
Empregos.com.br, 99jobs, BNE, Remotar, and the public-sector selection
notices CIEE publishes (`api-pp.ciee.org.br/api/editais/vitrine`).

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
| pay | when stated: structured fields from Ashby, Lever and Greenhouse, otherwise read from the description by `radar/pay.py` (it understands formats like `$54 — $60 USD`, `109,395.00 USD Annually` and `Bolsa auxílio: R$1.357,28/mês`). About 700 roles have it today. |
| skills | the skills a posting mentions, from a fixed list of about 80 in `radar/skills.py` (Python, C++, PyTorch, SQL, ROS, PLC, MATLAB, Embedded systems…), in English and Portuguese. Used by the résumé match on the site. Roles from the GitHub lists only have a title, so few skills are found for them. |

**Optional Claude labelling.** If the secret `ANTHROPIC_API_KEY` is set, new
postings are also sent (title, location and description) to Claude Haiku 4.5,
the cheapest current model. It fills the labels and the deadline more
accurately. It can never remove a posting; if it thinks a posting isn't for
students, it only adds the `unsure if student role` warning. At most 150 new
postings are labelled per run (`RADAR_LLM_MAX_ITEMS` changes that). Without the
key, everything works the same using the keyword rules.

---

## The website

The site is one plain HTML file, `docs/index.html` (no frameworks, no build
step). Each run rewrites `docs/data.json` and the page shows it.

**English and Português.** The site opens in Portuguese when the browser is
set to Portuguese, and in English otherwise; the **EN | PT** switch at the top
of every screen changes it and is remembered. Everything is translated,
including the résumé prompt, dates and numbers (`5.474`, `6 de out.`).
Postings themselves stay as their companies wrote them. All the texts live in
`STRINGS` at the top of the page's script, one `[English, Português]` pair per
text, so adding a language means adding a column.

**First visit: your profile.** The page asks three things: your field of
study (Engineering, Computing & IT, Math/physics/chemistry, Business &
economics, Law, Health, Biology & agriculture, Communication & design,
Education & humanities, Architecture, or Other), what you're studying for
(Bachelor's, Master's or PhD) and where your university is (Brazil, other
Latin America, United States, Canada, United Kingdom, Europe, Asia, Middle
East, Oceania, Africa). You can skip it and see everything unsorted. Change it
any time with the button at the top right. It is saved in your browser only.

**Field of study.** The bot labels each role with the fields it is aimed at
(`radar/fields.py`): from the title, or, when the title doesn't say, from the
course phrases in the description ("cursando Direito", "degree in Computer
Science"). The site then:

- shows your field and the related ones together (Engineering, Computing and
  the exact sciences; Health and Biology; Communication, Business and
  Humanities...), with roles for your own field first;
- **hides roles clearly meant only for other fields** (a nursing estágio for
  an engineering student). "Show roles for other fields", next to the number
  of roles and in the filters, brings them back, marked as long shots with
  the reason;
- always shows roles that don't say which field they want, and the roles you
  saved, applied to or hid.

With "Other" as your field nothing is hidden. Profiles made before this
question are asked once more (the other answers are kept).

**Fit.** With a profile, every role gets a dot: ● good fit, ◐ check something,
○ long shot. Open a row to see the reasons, for example:

- "Aimed at PhD or Master's students" (long shot for an undergrad)
- "Needs work authorization for the US or Canada" (when you study elsewhere)
- "Estágio requires enrollment at a Brazilian university" (when you study
  outside Brazil)
- "A job for after you graduate", "Mentions a graduation-year rule",
  "Might not be a student role"

Fit only sorts and flags. Every role stays on the page unless you filter it
out yourself.

**Résumé match (no AI inside vagaLume).** Click **Match my résumé** at the
top (or the link on the first screen):

1. Copy the prompt. It lists the skill names vagaLume knows, so the answer
   uses the same spelling.
2. Paste it into the AI chat you already use (ChatGPT, Gemini, Claude…) and
   attach your résumé. The prompt asks it to leave out your name and contact
   details and to answer with a small JSON summary: level, field, country,
   graduation month, where you can work, languages, areas, skills, the kind
   of roles you want and the months you're free.
3. Paste the answer back. vagaLume finds the `{ … }` part even if the AI
   wrapped it in text or a code block, and shows what it read.

The summary is stored in your browser only. With it:

- Every role gets a **match**: *Strong*, *Good*, *Some* or *Low*. It adds up
  the skills the posting mentions that are in your résumé (programming
  languages listed as alternatives, like "Java, Python or Go", count as one),
  whether the role is in one of your areas, and whether its title contains
  one of the roles you want. Strong and Good matches get a tag; open a row to
  see which skills match (✓) and which are missing.
- **Strong résumé match** and **Good match or better** filters under "For
  you", and a **Best résumé match** sort (the default; long shots still go
  last).
- Your **profile** is filled in from the summary.
- **Fit gets sharper:** countries where you can already work don't get the
  visa warning; a new-grad job is fine when you graduate within a year; an
  estágio says it's in Portuguese if you don't list Portuguese; and your free
  months replace UNESP's calendar in the month strip, the "Fits my breaks"
  filter, and a "runs outside the months you're free" note.

It's keyword matching, so it's a hint for sorting, not a verdict: read the
posting before deciding.

**Each row shows:**

| Column | What it is |
|---|---|
| Role | title (links to the posting), company, and at most two small tags: Applied, Strong match, New or Program. Under it, in amber or red, the first thing that might get in the way. |
| Where | the first location, then "+N more". Open the row for all of them. |
| Pay | when the posting states it, e.g. `$54–60/hr`, `R$1,357/mo`, `€1,800/mo`, `$94K–125K/yr`; a dash otherwise |
| When | for roles with a season, a 12-month strip, January to December. Grey months are UNESP semesters (Mar–Jun, Aug–Nov), or the months you're not free if your résumé summary lists them. The role's months are green when they fall in a break and amber when they clash with classes. Year-round roles just say so; a dash means the posting doesn't say. |
| Deadline | the date (a dash when none is stated), with the days left in red when it closes within 14 days |

On a phone the row is shorter: the title, the company and one line with the
place, the deadline and the pay.

Click a row to open it. On the left, **for you**: the résumé match with the
skills you have (✓) and the missing ones, then every fit reason. On the right,
the **details**: all locations, when, deadline, pay, labels and where it was
found. Below, the buttons: open the posting, mark as applied, save, hide.

**Around the list:**

- **Search** over role, company and city. Press `/` to jump to it; matches
  are highlighted.
- **Tabs:** All · New · Closing soon · Saved · Programs & schools, plus
  Applied and Hidden once you have marked something. Only New, Closing soon
  and the lists you build show a count.
- **Filters:** *For you* (good fit, no long shots, and with a résumé: strong
  match, good match or better), Area, Where and When (including a **Fits my
  breaks** shortcut). Under **More filters**: only roles that state pay, and
  the source. The small number on each chip is how many roles you'd see after
  clicking it, given the other filters you already picked. Click a selected
  chip again to turn it off.
- **Active filters** show as pills above the list. Click a pill's × to remove
  it, or "Clear all".
- **How to read** (next to the number of roles) explains the dots and the
  month strip.
- **Sort:** best résumé match (with a résumé), best fit (with a profile), deadline, newest, or company.
- **☆ Save** builds a shortlist (the Saved tab). **✕ Hide** moves a role to
  Hidden; it appears when you point at a row (on phones, it's inside the
  opened row). Inside an opened row you can also **Mark as applied**. All of this
  is saved in your browser, and clicking again undoes it.
- The list loads more rows by itself as you scroll.
- **Your filters live in the address bar** (for example
  `…/vagaLume/#area=ML&region=Europe`), so you can bookmark a view or send it
  to a friend.

**Turn it on (one time):** in the repository go to *Settings → Pages*, set
*Source* to **Deploy from a branch**, pick branch **main** and folder
**/docs**, and save. A minute later the site is live at
**https://pedrocamargolince.github.io/vagaLume/**, and it updates
after every daily run. The repository is public, so the site is public too.

To try it on your computer: `python -m http.server -d docs` and open
http://localhost:8000.

### Statuses that follow you everywhere

The Save, Applied and Hide buttons only remember things in one browser. For a status
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

**Gupy job types, CIEE and Super Estágios school levels, GitHub lists,
Google/Amazon queries:** edit `config/search.yaml`. **Brazilian employers on
SmartRecruiters or Workday:** add them to `smartrecruiters` or `workday_brazil`
in `config/companies.yaml` (the comments there explain how to read the id from
a careers-site address).

---

## Setting it up on GitHub

1. **Merge to the default branch.** GitHub runs scheduled workflows only on the
   default branch (`main`).
2. **Allow the workflow to push.** Go to *Settings → Actions → General →
   Workflow permissions* and pick **Read and write permissions**. The workflow
   commits `data/*.jsonl`, `reports/` and the website data.
3. **Turn on the website:** *Settings → Pages → Deploy from a branch → main,
   /docs*.
4. The schedule is daily at **09:00 Brasília (12:00 UTC)**. To run it now, open
   *Actions → vagaLume → Run workflow*.

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
address (https://pedrocamargolince.github.io/vagaLume/) and the digest
will link to it.

---

## Running it locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium   # headless browser, only needed for Meta

python -m radar                      # full run (about 8 minutes)
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
  pay.py           finds the pay in a description ("$54–60/hr", "R$1,357/mo")
  skills.py        finds the skills a posting mentions (for the résumé match)
  llm.py           optional Claude labelling (only with ANTHROPIC_API_KEY)
  db.py            SQLite storage, dedupe by id (hash of the URL)
  report.py        writes reports/latest.md
  site.py          writes docs/data.json (website) and docs/stats.json (README badges)
  notify.py        optional Telegram / email digest
  textutil.py      HTML to text, date parsing, deadline finding
  sources/         one module per source; each has a pure parse() function
docs/              the website: index.html (fixed) + data.json and stats.json (updated daily)
assets/            banner, demo GIF and screenshots used by the README
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
  A full run makes about 380 requests and opens 2 pages in the browser.
- **Repository size.** The database (`data/*.jsonl`, about 7 MB of text for
  17,000 roles), `docs/data.json` and `reports/latest.md` are committed every
  day: the database is the bot's memory (first-seen dates, your statuses, page
  hashes) and the JSON is the website, so they stay in git on purpose. To keep
  the daily growth small:
  - the database is text, one role per line, sorted, so git stores only the
    lines that changed and merges cleanly;
  - each role's "last seen" date is refreshed once a week, not every day (it
    only decides when a role unseen for 30 days is closed), so on a normal day
    only new and changed roles touch the file. In a test this kept the
    repository's growth around 25 KB a day, against about 60 KB with daily
    dates;
  - `.gitignore` keeps everything else out (the working `radar.db`, caches,
    virtual environments, editor folders), and `.gitattributes` marks the
    daily files as generated so GitHub collapses them in diffs.
