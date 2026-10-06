"""Keyword rules that attach labels to each opportunity.

These rules never remove anything. They only *describe* a posting:
which area it is in, when it happens, where it is, and what might be a
problem (warnings). You decide what to apply to.

Every list of keywords lives at the top of this file so you can tweak it
without touching the logic below.
"""

from __future__ import annotations

import re

from .models import NO_DEADLINE, Opportunity
from .pay import find_pay
from .textutil import find_deadline

# ---------------------------------------------------------------------------
# 1. Is this a student-level posting?
# ---------------------------------------------------------------------------
# A title containing one of these is clearly for students.
STRONG_STUDENT_WORDS = [
    r"intern", r"interns", r"internship", r"internships",
    r"est[áa]gio", r"estagi[áa]ri[oa]s?", r"est[áa]gios",
    r"co-?op", r"student", r"students", r"fellowship", r"fellows?",
    r"residency", r"summer", r"insight", r"explore",
    r"apprentice", r"apprenticeship", r"jovem aprendiz", r"aprendiz",
    r"working student", r"werkstudent", r"praktikum",
    r"scholar", r"scholars", r"scholarship", r"bolsa", r"inicia[çc][ãa]o cient[íi]fica",
    r"undergrad", r"undergraduate", r"ugrip", r"isternship",
]
# A title containing one of these *might* be for students -> label "unsure".
WEAK_STUDENT_WORDS = [
    r"program", r"programme", r"programa", r"school", r"course", r"curso",
    r"trainee", r"graduate", r"new grad", r"early career", r"early-career",
    r"university", r"campus", r"academy", r"bootcamp", r"resident", r"winter",
]
# Phrases that contain a weak word but are ordinary jobs, not programs.
# ("Technical Program Manager" is a job title, not a student program.)
NOT_A_PROGRAM = [
    r"program manager", r"programme manager", r"program management",
    r"programme management", r"program director", r"program lead",
    r"gerente de programa", r"program coordinator", r"program analyst",
    r"program specialist", r"program officer", r"school psychologist",
    r"graduate recruiter", r"university recruiter", r"campus recruiter", r"dean of students",
    r"member of technical staff",  # AI labs' generic title, not a "staff" (senior) level
]
def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(rf"\b{p}\b", text, re.I) for p in patterns)


# If a title has a seniority word, a *clear* student word must also be there.
SENIOR_WORDS = [r"senior", r"sr\.?", r"staff", r"principal", r"distinguished", r"director", r"head of", r"vp", r"vice president", r"lead"]
CLEAR_STUDENT_WORDS = [r"intern", r"internship", r"student", r"est[áa]gio", r"estagi[áa]ri[oa]", r"co-?op", r"apprentice", r"summer", r"fellowship"]


def student_level(title: str) -> str:
    """Return "yes", "unsure" or "no" for a job title."""
    cleaned = title
    for phrase in NOT_A_PROGRAM:
        cleaned = re.sub(phrase, " ", cleaned, flags=re.I)
    if _any(SENIOR_WORDS, cleaned) and not _any(CLEAR_STUDENT_WORDS, cleaned):
        return "no"  # e.g. "Senior Manager, Fellows Program" is a staff job
    if _any(STRONG_STUDENT_WORDS, cleaned):
        return "yes"
    if _any(WEAK_STUDENT_WORDS, cleaned):
        return "unsure"
    return "no"


# ---------------------------------------------------------------------------
# 2. Area
# ---------------------------------------------------------------------------
# Checked in this order; the first match wins. Quant first because
# "Quantitative Researcher" should be quant, not research.
AREA_RULES: list[tuple[str, list[str]]] = [
    ("quant", [r"quant\w*", r"trading", r"trader", r"market making", r"algorithmic trading"]),
    ("ML", [
        r"machine learning", r"ml", r"ai", r"a\.i\.", r"artificial intelligence", r"deep learning",
        r"llms?", r"nlp", r"natural language", r"computer vision", r"reinforcement learning",
        r"generative", r"genai", r"intelig[êe]ncia artificial", r"aprendizado de m[áa]quina",
        r"neural", r"perception", r"robot learning", r"foundation models?", r"alignment",
        r"interpretability", r"mlops", r"applied scientist",
    ]),
    # "Data Scientist" should be data, not research, so check it first.
    ("data", [r"data scien\w*", r"ci[êe]ncia de dados", r"cientista de dados"]),
    ("research", [r"research", r"researcher", r"pesquisa", r"pesquisador\w*", r"scientist", r"phd"]),
    ("data", [
        r"data", r"dados", r"analytics", r"analyst", r"business intelligence", r"bi",
        r"statistic\w*", r"estat[íi]stica", r"analista",
    ]),
    ("hardware", [
        r"hardware", r"asic", r"fpga", r"silicon", r"chip", r"embedded", r"embarcad\w*",
        r"electrical", r"el[ée]tric\w*", r"electronic\w*", r"eletr[ôo]nic\w*", r"rf", r"analog",
        r"firmware", r"verification", r"vlsi", r"automa[çc][ãa]o", r"automation", r"control systems?",
        r"controls", r"robotics", r"rob[óo]tica", r"mechanical", r"mec[âa]nic\w*", r"mechatronics",
        r"plc", r"clp", r"thermal", r"manufacturing", r"produ[çc][ãa]o",
    ]),
    ("SWE", [
        r"software", r"swe", r"developer", r"desenvolvedor\w*", r"desenvolvimento", r"engineer\w*",
        r"engenharia de software", r"backend", r"back-end", r"frontend", r"front-end", r"full[- ]?stack",
        r"devops", r"infrastructure", r"cloud", r"security", r"seguran[çc]a", r"programa[çc][ãa]o",
        r"mobile", r"android", r"ios", r"web", r"sre", r"platform", r"tecnologia", r"ti", r"sistemas",
        r"computer science", r"ci[êe]ncia da computa[çc][ãa]o", r"programador\w*",
    ]),
]


def classify_area(title: str, description: str = "") -> str:
    """Pick one area. The title decides; the description is only a fallback."""
    for text in (title, description[:600]):
        for area, words in AREA_RULES:
            if _any(words, text):
                return area
    return "other"


# ---------------------------------------------------------------------------
# 3. Season (when the opportunity happens)
# ---------------------------------------------------------------------------
SEASON_RULES: list[tuple[str, list[str]]] = [
    # Brazilian summer break. "verão" means the *southern* summer.
    ("Dec–Feb", [
        r"ver[ãa]o", r"est[áa]gio de f[ée]rias", r"f[ée]rias de (?:fim de ano|ver[ãa]o)",
        r"dec(?:ember)?\s*[-–]\s*feb\w*", r"dezembro a fevereiro", r"janeiro a fevereiro",
        r"jan(?:uary)?\s*[-–]\s*feb\w*", r"southern summer",
    ]),
    ("Jul", [r"f[ée]rias de julho", r"mid-year break", r"july break", r"curso de julho"]),
    ("May–Aug", [r"summer", r"may\s*[-–]\s*aug\w*", r"june\s*[-–]\s*aug\w*"]),
    ("year-round", [
        # "spring" alone would match "Java Spring", so we require a term word.
        r"(?:fall|autumn|spring|winter)(?:/\w+)?\s+(?:20\d\d|semester|term|co-?op|internship|intern)",
        r"co-?op", r"off-?cycle", r"year-round", r"part[- ]time", r"meio per[íi]odo",
        r"(?:3|4|6|12)[- ]month (?:internship|program|placement)",
        r"est[áa]gio", r"estagi[áa]ri[oa]", r"student researcher", r"working student",
    ]),
]


def classify_season(title: str, description: str = "", hints: list[str] | None = None) -> str:
    """Guess the season from the title first, then from hints and the description."""
    for text in (title, " ".join(hints or []), description[:1500]):
        for season, words in SEASON_RULES:
            if _any(words, text):
                return season
    return "unknown"


# ---------------------------------------------------------------------------
# 4. Region (where it is). A posting can be in several regions.
# ---------------------------------------------------------------------------
BRAZIL = [
    r"brazil", r"brasil", r"s[ãa]o paulo", r"rio de janeiro", r"belo horizonte", r"curitiba",
    r"porto alegre", r"florian[óo]polis", r"campinas", r"sorocaba", r"recife", r"bras[íi]lia",
    r"salvador", r"fortaleza", r"manaus", r"goi[âa]nia", r"ribeir[ãa]o preto", r"s[ãa]o carlos",
    r"s[ãa]o jos[ée] dos campos", r"joinville", r"blumenau", r"barueri", r"osasco", r"jundia[íi]",
    r"uberl[âa]ndia", r"londrina", r"santos", r"niter[óo]i", r"distrito federal", r"minas gerais",
    r"santa catarina", r"paran[áa]", r"rio grande do sul", r"pernambuco", r"bahia", r"cear[áa]",
    r"goi[áa]s", r"esp[íi]rito santo", r"amazonas",
    # A location written only as "Remoto" (Portuguese) is almost always a Brazilian job.
    r"remoto",
]
# Two-letter state codes that do not clash with US state codes.
BRAZIL_STATE_CODES = r",\s*(SP|RJ|MG|RS|BA|PE|CE|DF|GO|ES|AM|PB|RN|PI|SE|TO|RO|RR|AP|AC|PR)\b|\bBRA\b"
LATAM = [
    r"MEX", r"ARG", r"CHL", r"COL", r"PER", r"URY", r"CRI",  # ISO country codes (checked case-sensitively below)
    r"mexico", r"m[ée]xico", r"guadalajara", r"monterrey", r"argentina", r"buenos aires", r"chile",
    r"santiago", r"colombia", r"bogot[áa]", r"medell[íi]n", r"peru", r"lima", r"uruguay", r"montevideo",
    r"costa rica", r"latam", r"latin america", r"am[ée]rica latina",
]
US_CANADA = [
    r"usa", r"united states", r"u\.s\.", r"us remote", r"remote in usa", r"canada", r"toronto",
    r"vancouver", r"montr[ée]al", r"waterloo", r"ottawa", r"new york", r"nyc", r"san francisco",
    r"seattle", r"boston", r"chicago", r"austin", r"mountain view", r"palo alto", r"menlo park",
    r"sunnyvale", r"santa clara", r"san jose", r"los angeles", r"pittsburgh", r"atlanta", r"miami",
    r"denver", r"redmond", r"bay area", r"washington,? d\.?c\.?", r"san diego", r"philadelphia",
    r"bellevue", r"princeton", r"north america", r"cambridge, ma", r"california", r"texas",
    r"massachusetts", r"new jersey", r"illinois", r"colorado", r"virginia", r"maryland", r"michigan",
    r"ohio", r"pennsylvania", r"florida", r"oregon", r"utah", r"arizona", r"north carolina",
    r"south carolina", r"minnesota", r"wisconsin", r"missouri", r"tennessee", r"connecticut",
    r"alabama", r"ontario", r"british columbia", r"quebec", r"alberta", r"iowa", r"indiana", r"idaho",
    r"georgia", r"kansas", r"kentucky", r"nevada", r"oklahoma", r"south sf", r"americas",
]
# US state codes + Canadian provinces that are unambiguous...
US_STATE_CODES = (
    r",\s*(AK|AZ|CA|CT|FL|GA|HI|IA|KS|KY|LA|ME|MD|MI|MN|MO|NE|NV|NH|NJ|NM|NY|"
    r"NC|ND|OH|OK|OR|RI|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|ON|BC|QC|AB)\b|\b(USA|CAN|SF|LA|NYC)\b"
)
# ...and codes that could also be a Brazilian state (SC, PA, MT, MS, AL, MA)
# or a country (DE, CO, AR, IN, IL, ID). These only count when no other
# region was recognised by name ("Berlin, DE" stays Europe only).
US_AMBIGUOUS_CODES = r",\s*(SC|PA|MT|MS|AL|MA|DE|CO|AR|IN|IL|ID)\b"
EUROPE = [
    r"uk", r"united kingdom", r"england", r"london", r"edinburgh", r"manchester", r"oxford", r"bristol",
    r"ireland", r"dublin", r"france", r"paris", r"germany", r"deutschland", r"berlin", r"munich",
    r"m[üu]nchen", r"hamburg", r"frankfurt", r"netherlands", r"amsterdam", r"switzerland", r"zurich",
    r"z[üu]rich", r"geneva", r"lausanne", r"austria", r"vienna", r"klosterneuburg", r"spain", r"madrid",
    r"barcelona", r"portugal", r"lisbon", r"porto(?! alegre)", r"italy", r"milan", r"rome", r"sweden", r"stockholm",
    r"denmark", r"copenhagen", r"norway", r"oslo", r"finland", r"helsinki", r"poland", r"warsaw",
    r"krak[óo]w", r"prague", r"czech", r"belgium", r"brussels", r"ghent", r"luxembourg", r"budapest",
    r"hungary", r"romania", r"bucharest", r"greece", r"athens", r"estonia", r"tallinn", r"europe", r"emea",
    r"cambridge, uk", r"t[üu]bingen", r"lyon", r"grenoble", r"serbia", r"belgrade", r"ukraine", r"kyiv",
    r"slovakia", r"bratislava", r"croatia", r"zagreb", r"bulgaria", r"sofia", r"lithuania", r"vilnius",
    r"latvia", r"riga", r"slovenia", r"ljubljana", r"cyprus", r"malta", r"iceland", r"zaragoza",
    r"GBR", r"DEU", r"FRA", r"NLD", r"CHE", r"AUT", r"ESP", r"PRT", r"ITA", r"SWE", r"DNK", r"NOR",
    r"FIN", r"POL", r"CZE", r"SVK", r"BEL", r"IRL", r"ROU", r"HUN", r"GRC", r"SRB", r"UKR", r"UA",
]
ASIA_ME = [  # Asia, Middle East and Oceania
    r"singapore", r"hong kong", r"china", r"shanghai", r"beijing", r"shenzhen", r"taiwan", r"taipei",
    r"hsinchu", r"japan", r"tokyo", r"okinawa", r"korea", r"seoul", r"india", r"bangalore", r"bengaluru",
    r"hyderabad", r"pune", r"mumbai", r"delhi", r"gurgaon", r"gurugram", r"chennai", r"noida", r"israel",
    r"tel aviv", r"haifa", r"dubai", r"abu dhabi", r"uae", r"united arab emirates", r"saudi", r"thuwal",
    r"riyadh", r"qatar", r"doha", r"australia", r"sydney", r"melbourne", r"new zealand", r"vietnam",
    r"philippines", r"manila", r"malaysia", r"kuala lumpur", r"indonesia", r"jakarta", r"thailand",
    r"bangkok", r"apac", r"asia",
    r"SGP", r"JPN", r"KOR", r"CHN", r"HKG", r"TWN", r"IND", r"ISR", r"ARE", r"SAU", r"AUS", r"NZL",
]


def _mentions(patterns: list[str], text: str) -> bool:
    """Words match case-insensitively; ALL-CAPS codes (GBR, SGP...) only as written."""
    for p in patterns:
        flags = 0 if re.fullmatch(r"[A-Z]{2,3}", p) else re.I
        if re.search(rf"\b{p}\b", text, flags):
            return True
    return False


def classify_regions(location: str, remote: bool = False) -> list[str]:
    """Return every region that the location string mentions."""
    regions: list[str] = []
    checks = [
        ("Brazil", BRAZIL, BRAZIL_STATE_CODES),
        ("LatAm", LATAM, None),
        ("US/Canada", US_CANADA, US_STATE_CODES),
        ("Europe", EUROPE, None),
        ("Asia/ME", ASIA_ME, None),
    ]
    for name, words, codes in checks:
        if _mentions(words, location) or (codes is not None and re.search(codes, location)):
            regions.append(name)
    # "Boise, ID" -> US, but "Berlin, DE" was already recognised as Europe.
    if not regions and re.search(US_AMBIGUOUS_CODES, location):
        regions.append("US/Canada")
    if remote or re.search(r"\bremote\b|\bremoto\b|\banywhere\b|\bworldwide\b|home[- ]based", location, re.I):
        regions.append("remote")
    return regions or ["unknown"]


# ---------------------------------------------------------------------------
# 5. Warnings
# ---------------------------------------------------------------------------
W_US_AUTH = "US work auth?"
W_PHD = "PhD-level?"
W_GRAD_YEAR = "grad-year limit?"
W_UNSURE = "unsure if student role"
W_NEW_GRAD = "new-grad role (after graduation)"

US_AUTH_TEXT = [
    r"work authori[sz]ation", r"authori[sz]ed to work", r"visa sponsorship", r"sponsorship",
    r"u\.?s\.? citizen\w*", r"security clearance", r"green card", r"permanent resident", r"itar",
    r"export control",
]
PHD_TITLE = [r"ph\.?d", r"doctoral", r"doutorado", r"ms/phd", r"m\.s\./ph\.d", r"🎓"]
PHD_TEXT = [
    r"pursuing a ph\.?d", r"ph\.?d\.? (?:student|candidate|program)", r"enrolled in a ph\.?d",
    r"doctoral (?:student|candidate|program)", r"doutorando", r"advanced degree required",
]
NEW_GRAD_TITLE = [
    r"new grad\w*", r"new college grad\w*", r"recent grad\w*", r"university grad\w*",
    r"early career", r"early-career", r"graduate (?:engineer|program|programme|scheme|analyst)",
]
GRAD_YEAR_TEXT = [
    r"class of 20\d\d", r"graduat\w*[^.\n]{0,50}\b20\d\d\b", r"\b20\d\d graduates?",
    r"penultimate[- ]year", r"final[- ]year", r"previs[ãa]o de (?:formatura|conclus[ãa]o)",
    r"formatura (?:entre|em|at[ée])", r"conclus[ãa]o (?:do curso )?(?:entre|em|at[ée])",
    r"expected graduation", r"graduation date",
]


def find_warnings(opp: Opportunity, level: str, regions: list[str]) -> list[str]:
    """Collect warnings. They are hints with a '?', not verdicts."""
    text = f"{opp.title}\n{opp.description}"
    hints = set(opp.hints)
    warnings: list[str] = []
    if "US/Canada" in regions or _any(US_AUTH_TEXT, text) or hints & {"no-sponsorship", "us-citizen"}:
        warnings.append(W_US_AUTH)
    if _any(PHD_TITLE, opp.title) or _any(PHD_TEXT, opp.description) or "advanced-degree" in hints:
        warnings.append(W_PHD)
    if _any(GRAD_YEAR_TEXT, text):
        warnings.append(W_GRAD_YEAR)
    if "new-grad" in hints or (level != "yes" and _any(NEW_GRAD_TITLE, opp.title)):
        warnings.append(W_NEW_GRAD)  # sure it's not a student role, but you asked to see these
    elif level != "yes":
        warnings.append(W_UNSURE)
    return warnings


# ---------------------------------------------------------------------------
# 6. Calendar note: does it clash with UNESP semesters (Mar–Jul, Aug–Dec)?
# ---------------------------------------------------------------------------
CALENDAR_NOTES = {
    "Dec–Feb": "fits the UNESP summer break (Dec–Feb)",
    "Jul": "fits the UNESP July break",
    "May–Aug": "overlaps semesters: May–Jul clashes with Mar–Jul and Aug with Aug–Dec; needs a leave or remote deal",
    "year-round": "runs during semesters (Mar–Jul, Aug–Dec); OK only if part-time/remote or you take a semester off",
    "unknown": "dates unknown; compare with UNESP semesters (Mar–Jul, Aug–Dec)",
}


def calendar_note(season: str) -> str:
    return CALENDAR_NOTES.get(season, CALENDAR_NOTES["unknown"])


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------
def level_for(opp: Opportunity) -> str:
    """Student level, taking the source's hints into account."""
    if "student" in opp.hints or "new-grad" in opp.hints:
        return "yes"  # the source itself says it is a student role (or a curated list)
    if "unsure-student" in opp.hints:
        return "unsure"
    return student_level(opp.title)


def apply_rules(opp: Opportunity) -> Opportunity:
    """Fill in area, season, regions, warnings, calendar note and deadline."""
    level = level_for(opp)
    preset = opp.preset
    opp.regions = list(preset.get("regions") or classify_regions(opp.location, opp.remote))  # type: ignore[arg-type]
    opp.area = str(preset.get("area") or classify_area(opp.title, opp.description))
    # Sources can suggest an area ("area:quant") used when the rules find nothing.
    suggested = [hint.split(":", 1)[1] for hint in opp.hints if hint.startswith("area:")]
    if opp.area == "other" and suggested:
        opp.area = suggested[0]
    opp.season = str(preset.get("season") or classify_season(opp.title, opp.description, opp.hints))
    opp.warnings = find_warnings(opp, level, opp.regions)
    for extra in preset.get("warnings") or []:  # type: ignore[union-attr]
        if extra not in opp.warnings:
            opp.warnings.append(str(extra))
    opp.calendar_note = calendar_note(opp.season)
    if opp.deadline == NO_DEADLINE or not opp.deadline:
        opp.deadline = find_deadline(opp.description) or NO_DEADLINE
    if not opp.pay:
        opp.pay = find_pay(opp.description)
    opp.labeled_by = "rules"
    return opp


def is_student_candidate(title: str) -> bool:
    """Used by sources that list *all* jobs: keep anything that might be for students."""
    return student_level(title) != "no"
