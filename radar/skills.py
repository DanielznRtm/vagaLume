"""Find the skills a posting asks for (Python, PyTorch, ROS, PLC...).

The website compares these with the skills from your résumé (see "Match my
résumé" on the site). It is plain keyword matching: no AI involved.

Each entry is (name shown on the site, regular expression). Patterns ignore
upper/lower case, except inside "(?-i:...)": short words like "R", "Go",
"Rust" or "ML" only count when written exactly like that.
Patterns include Portuguese spellings where they differ, for Gupy postings.

The website also gives this list of names to the AI prompt, so the skills
from your résumé use exactly the same spelling.
"""

from __future__ import annotations

import re

SKILLS: list[tuple[str, str]] = [
    # --- programming languages ---------------------------------------------
    ("Python", r"\bpython\b|\bpyspark\b"),
    ("C++", r"\bC\+\+|\bcpp\b"),
    ("C", r"(?-i:\bC/C\+\+|\bC (?:programming|language)\b|(?:Python|Java|C\+\+|Rust|Go),? (?:and |or )?C\b(?![+#]))"),
    ("C#", r"(?-i:\bC#|\.NET\b)"),
    ("Java", r"\bjava\b(?!\s*script)"),
    ("JavaScript", r"\bjavascript\b|(?-i:\bJS\b)"),
    ("TypeScript", r"\btypescript\b"),
    ("Go", r"\bgolang\b|(?-i:(?:Python|Java|Rust|C\+\+|Kotlin),? (?:and |or )?Go\b|\bGo,? (?:and |or )(?:Python|Java|Rust|C\+\+))"),
    ("Rust", r"(?-i:\bRust\b)"),
    ("Kotlin", r"\bkotlin\b"),
    ("Swift", r"(?-i:\bSwift\b)"),
    ("Scala", r"(?-i:\bScala\b)"),
    ("OCaml", r"\bocaml\b"),
    ("Haskell", r"\bhaskell\b"),
    ("R", r"(?-i:\bR (?:programming|language|Studio)\b|\bRStudio\b|(?:Python|SQL|MATLAB|SAS),? (?:and |or |/)?R\b(?![&$+])|\bR,? (?:and |or |/)(?:Python|SQL|MATLAB))"),
    ("MATLAB", r"\bmatlab\b"),
    ("SQL", r"(?-i:\bSQL\b)|\bpostgres(?:ql)?\b|\bmysql\b|\bT-SQL\b|\bBigQuery\b|\bSnowflake\b"),
    ("Bash", r"\bbash\b|\bshell script"),
    ("Verilog", r"\b(?:system ?)?verilog\b"),
    ("VHDL", r"\bvhdl\b"),
    # --- machine learning and data -----------------------------------------
    ("Machine learning", r"machine learning|(?-i:\bML\b)|aprendizado de m[áa]quina|aprendizagem de m[áa]quina"),
    ("Deep learning", r"deep learning|neural net(?:work)?s?|redes neurais|aprendizado profundo"),
    ("LLMs", r"(?-i:\bLLMs?\b)|large language models?|generative AI|\bgen ?AI\b|IA generativa"),
    ("NLP", r"(?-i:\bNLP\b)|natural language|linguagem natural"),
    ("Computer vision", r"computer vision|vis[ãa]o computacional|image processing|processamento de imagens|\bopencv\b|object detection"),
    ("Reinforcement learning", r"reinforcement learning|aprendizado por refor[çc]o"),
    ("PyTorch", r"\bpytorch\b|\btorch\b"),
    ("TensorFlow", r"\btensorflow\b"),
    ("JAX", r"(?-i:\bJAX\b)"),
    ("Keras", r"\bkeras\b"),
    ("scikit-learn", r"\bscikit-?learn\b|\bsklearn\b"),
    ("Hugging Face", r"\bhugging ?face\b"),
    ("Pandas", r"\bpandas\b"),
    ("NumPy", r"\bnumpy\b"),
    ("CUDA", r"\bCUDA\b"),
    ("Statistics", r"\bstatistics\b|\bstatistical\b|estat[íi]stica"),
    ("Probability", r"\bprobability\b|\bstochastic\b|probabilidade"),
    ("Linear algebra", r"linear algebra|[áa]lgebra linear"),
    ("Optimization", r"\b(?:mathematical|numerical|convex|combinatorial) optimi[sz]ation\b|\blinear programming\b|algoritmos de otimiza[çc][ãa]o|otimiza[çc][ãa]o (?:matem[áa]tica|num[ée]rica)|pesquisa operacional"),
    ("Time series", r"time[- ]series|s[ée]ries temporais"),
    ("Data analysis", r"data analy(?:sis|tics)|an[áa]lise de dados"),
    ("Data structures", r"data structures|estruturas? de dados"),
    ("Spark", r"(?-i:\bSpark\b)|\bpyspark\b"),
    ("Kafka", r"\bkafka\b"),
    ("Airflow", r"\bairflow\b"),
    ("Excel", r"(?-i:\bExcel\b)(?! (?:at|in)\b)"),
    ("Power BI", r"\bpower ?bi\b"),
    ("Tableau", r"\btableau\b"),
    # --- software engineering ----------------------------------------------
    ("Linux", r"\blinux\b|\bunix\b"),
    ("Git", r"\bgit\b|\bgithub\b|\bgitlab\b"),
    ("Docker", r"\bdocker\b"),
    ("Kubernetes", r"\bkubernetes\b|\bk8s\b"),
    ("AWS", r"(?-i:\bAWS\b)|amazon web services"),
    ("GCP", r"(?-i:\bGCP\b)|google cloud"),
    ("Azure", r"\bazure\b"),
    ("CI/CD", r"(?-i:\bCI ?/ ?CD\b)|continuous integration"),
    ("Distributed systems", r"distributed systems?|sistemas distribu[íi]dos"),
    ("React", r"(?-i:\bReact\b)|\breact\.?js\b"),
    ("Node.js", r"\bnode\.?js\b"),
    ("Django", r"\bdjango\b"),
    ("FastAPI", r"\bfastapi\b|\bflask\b"),
    ("REST APIs", r"(?-i:\bREST(?:ful)?\b)"),
    ("Android", r"\bandroid\b"),
    ("iOS", r"(?-i:\biOS\b)"),
    # --- hardware, robotics and automation ---------------------------------
    ("Robotics", r"\brobotics?\b|rob[óo]tica|\brobots?\b"),
    ("ROS", r"(?-i:\bROS ?2?\b)"),
    ("Control systems", r"(?<!version )control (?:systems?|theory|engineering)|sistemas de controle|model predictive control|(?-i:\bPID\b|\bMPC\b)"),
    ("PLC", r"(?-i:\bPLCs?\b|\bCLPs?\b)|programmable logic controllers?|controladores? l[óo]gicos?"),
    ("SCADA", r"\bSCADA\b|supervis[óo]rios?\b"),
    ("Embedded systems", r"\bembedded (?:systems?|software|firmware|C\b|C\+\+|linux|devices?|hardware|programming|development|engineering|electronics)|embarcad[oa]s?|\bfirmware\b|microcontroll?ers?|microcontroladore?s?|\bRTOS\b|\bSTM32\b"),
    ("Arduino", r"\barduino\b"),
    ("Raspberry Pi", r"raspberry ?pi"),
    ("FPGA", r"\bFPGAs?\b"),
    ("Electronics", r"\belectronics\b|eletr[ôo]nica|circuit design|analog circuits?"),
    ("PCB design", r"(?-i:\bPCBs?\b)|printed circuit"),
    ("Signal processing", r"signal processing|(?-i:\bDSP\b)|processamento de sinais"),
    ("IoT", r"(?-i:\bIoT\b)|internet of things|internet das coisas"),
    ("Simulink", r"\bsimulink\b"),
    ("LabVIEW", r"\blabview\b"),
    ("CAD", r"(?<!\d )(?<!\()(?-i:\bCAD\b)(?!\s*(?:\$|\d|\)|hourly|per\b))|solidworks|autocad|fusion 360|\bcatia\b"),
    # --- markets -----------------------------------------------------------
    ("Financial markets", r"financial markets|\btrading\b|\bderivatives\b|options pricing|mercado financeiro"),
    # --- beyond tech (added October 2026; only ever add at the END: the Telegram link code
    # numbers skills by position) ---------------------------------------------------------
    # Law
    ("Tax law", r"direito tribut|tax law|\btributário\b|\btributario\b"),
    ("Labor law", r"direito do trabalho|trabalhista|labou?r law|employment law"),
    ("Litigation", r"contencioso|litigation|processual|peti[çc][õo]es|audi[êe]ncias"),
    ("Contracts", r"contratos|contract (?:drafting|review|law)|elabora[çc][ãa]o de contratos"),
    ("Corporate law", r"direito societ|corporate law|societário|societario|\bM&A\b"),
    # Not "in compliance with applicable laws" (equal-opportunity text): the field itself.
    ("Compliance", r"(?:analista|área|area|programa|program|equipe|time|team|gest[ãa]o|risk|risco|regulatory)\s+(?:de\s+)?compliance"
                   r"|compliance\s+(?:analyst|program|team|risk|regulat\w*|officer|e\s+riscos)|\bKYC\b|\bAML\b|lavagem de dinheiro"),
    ("Data protection (LGPD/GDPR)", r"\blgpd\b|\bgdpr\b|prote[çc][ãa]o de dados|data protection|privacy law"),
    ("Legal research", r"pesquisa jur[íi]dica|jurisprud[êe]ncia|legal research"),
    # Health
    ("Patient care", r"cuidados? (?:ao|com o) paciente|patient care|assist[êe]ncia ao paciente|atendimento ao paciente"),
    ("Nursing procedures", r"procedimentos de enfermagem|curativos|sinais vitais|vital signs|administra[çc][ãa]o de medicamentos"),
    ("Pharmacology", r"farmacolog|pharmacolog|dispensa[çc][ãa]o"),
    ("Clinical analysis", r"an[áa]lises cl[íi]nicas|clinical (?:analysis|laboratory)|coleta de (?:sangue|material)"),
    ("Public health", r"sa[úu]de p[úu]blica|public health|\bSUS\b|vigil[âa]ncia (?:sanit|epidem)"),
    ("Nutrition", r"\bnutri[çc][ãa]o\b|\bnutrition\b|dietoterapia"),
    ("Physiotherapy", r"fisioterap|physiotherap|reabilita[çc][ãa]o"),
    ("Psychology", r"psicolog|psycholog|\bpsicodiagn"),
    # Business
    ("Financial analysis", r"an[áa]lise financeira|financial analysis|fluxo de caixa|cash flow|\bDRE\b|demonstra[çc][õo]es financeiras"),
    ("Accounting", r"contabilidade|accounting|concilia[çc][ãa]o|lan[çc]amentos cont[áa]beis|\bIFRS\b"),
    ("Valuation", r"\bvaluation\b|\bDCF\b|avalia[çc][ãa]o de empresas"),
    ("Financial modeling", r"modelagem financeira|financial model"),
    ("SAP", r"(?-i:\bSAP\b)"),
    ("CRM", r"(?-i:\bCRM\b)|salesforce|hubspot"),
    # Not "our sales team" in a company blurb: selling itself.
    ("Sales", r"t[ée]cnicas de vendas|\bvendas\b(?! da empresa)|sales (?:experience|skills|techniques|pipeline|process|targets)|inside sales"
              r"|\bB2B sales|prospec[çc][ãa]o de clientes|negocia[çc][ãa]o com (?:clientes|fornecedores)"),
    ("Supply chain", r"supply chain|log[íi]stica|\bcompras\b|procurement|suprimentos|gest[ãa]o de estoques?|controle de estoque|inventory management"),
    ("Project management", r"gest[ãa]o de projetos|gerenciamento de projetos|project management|\bPMBOK\b|\bscrum\b|\bkanban\b"),
    ("Lean / Six Sigma", r"\blean\b|six sigma|seis sigma|melhoria cont[íi]nua|\bkaizen\b"),
    # Not "your recruiter will contact you" or "Recruiting Partner": recruiting as the work.
    ("Recruiting (HR)", r"recrutamento e sele[çc][ãa]o|\bR&S\b|sele[çc][ãa]o de pessoas|departamento pessoal|folha de pagamento|\bpayroll\b"
                        r"|talent acquisition|full[- ]cycle recruiting|sourcing (?:of )?candidates|triagem de curr[íi]culos"
                        r"|(?:área|estágio|estagi[áa]ri[oa]|assistente|analista) (?:de |em )?(?:recrutamento|recruiting)|recruiting intern"),
    ("Customer service", r"atendimento ao cliente|customer service|customer success|sucesso do cliente"),
    # Communication and design
    ("Digital marketing", r"marketing digital|digital marketing|google ads|meta ads|tr[áa]fego pago|performance marketing"),
    ("SEO", r"(?-i:\bSEO\b)"),
    # Not "follow us on Instagram": producing for social media.
    ("Social media", r"gest[ãa]o de (?:redes|m[íi]dias) sociais|conte[úu]do para (?:as )?redes sociais|social media (?:management|marketing|strategy|content|analytics)"
                     r"|(?:criar|criação de|produzir|produção de|planejamento de) (?:posts|conte[úu]do)|community management|linkedin content"),
    ("Copywriting", r"copywrit|reda[çc][ãa]o publicit|produ[çc][ãa]o de conte[úu]do|content writing"),
    ("Adobe Photoshop / Illustrator", r"photoshop|illustrator|indesign|adobe creative"),
    ("Figma", r"\bfigma\b"),
    ("Canva", r"\bcanva\b"),
    ("Video editing", r"edi[çc][ãa]o de v[íi]deo|video editing|premiere|after effects|davinci"),
    # Engineering, architecture and sciences
    ("Revit / BIM", r"\brevit\b|(?-i:\bBIM\b)"),
    ("Quality management (ISO)", r"\bISO 9001\b|gest[ãa]o da qualidade|quality management|\bPDCA\b|\bFMEA\b"),
    ("Workplace safety (NR)", r"\bNR-?\d+\b|seguran[çc]a do trabalho|occupational safety|\bEHS\b"),
    ("Stata / SPSS", r"\bstata\b|\bspss\b|\beviews\b"),
    ("Econometrics", r"econometri"),
    ("Lab techniques", r"t[ée]cnicas laboratoriais|lab(?:oratory)? techniques|\bPCR\b|cromatografia|chromatography|\bHPLC\b"),
    ("GIS", r"(?-i:\bGIS\b)|\bSIG\b|\bqgis\b|\barcgis\b|geoprocessamento"),
    # Education
    ("Teaching", r"doc[êe]ncia|\bteaching\b|regência de classe|plano de aula|lesson plan"),
]

NAMES = [name for name, _ in SKILLS]
_COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in SKILLS]


def find_skills(text: str) -> list[str]:
    """Every skill name mentioned in `text`, in the order of SKILLS."""
    if not text:
        return []
    return [name for name, pattern in _COMPILED if pattern.search(text)]
