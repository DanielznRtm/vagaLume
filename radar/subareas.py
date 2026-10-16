"""Sub-areas inside each market section: Tributário in Law, Enfermagem in
Health, Finanças in Business...

The site's "Área" filter has one group per section (the fields in
radar/fields.py) with these sub-areas as chips, so a law student can pick
Tributário and Trabalhista, and an engineer can add Finanças. Tech roles keep
their own areas (ML, Software, Data... in radar/labels.py).

Read from the title only, without accents: descriptions mention everything
(an engineering estágio's text talks about people, quality, safety...).
The keys never change (they are in links and saved filters); add new ones at
will. Labels for the site are in docs/index.html ("sub.<key>").
"""

from __future__ import annotations

import re
import unicodedata

# key -> (section, pattern). The section is a field from radar/fields.py.
SUBAREAS: dict[str, tuple[str, str]] = {
    # Law
    "tributario": ("direito", r"tribut|\btax law|direito fiscal"),
    "trabalhista": ("direito", r"trabalhist|\blabou?r law|employment law"),
    "contencioso": ("direito", r"contencios|civel|direito civil|civil litigation|processual|litigation|litigio"),
    "societario": ("direito", r"societari|\bm&a\b|fusoes|corporate law|mercado de capitais|bancario"),
    "contratos": ("direito", r"contrat(?:o|ual)|imobiliari|real estate law"),
    "regulatorio": ("direito", r"regulatori|compliance|lgpd|privacidade|privacy|\bprotecao de dados"),
    "penal": ("direito", r"\bpenal\b|criminal"),
    "consumidor": ("direito", r"consumidor|consumer law"),
    # Health
    "enfermagem": ("saude", r"enfermag|nursing|\bnurse"),
    "medicina": ("saude", r"medicina(?! veterin)|\bmedical student|\bmedic(?:o|al) "),
    "farmacia": ("saude", r"farmac|pharmac"),
    "nutricao": ("saude", r"nutri[cç]|nutrition|dietetic"),
    "psicologia": ("saude", r"psicolog|psycholog"),
    "fisioterapia": ("saude", r"fisioterap|physiotherap|terapia ocupacional"),
    "odontologia": ("saude", r"odontolog|dentist|dental"),
    "veterinaria": ("saude", r"veterinar"),
    "analises": ("saude", r"analises clinicas|biomedic|laboratorio clinico|patologia|radiolog"),
    "esporte": ("saude", r"educacao fisica|esporte|natacao|personal trainer|academia(?! de)|\bsports?\b"),
    # Business
    "financas": ("negocios", r"financ|economi|tesouraria|treasury|investiment|investment|credito|\bcredit\b|banking|bancari|\bfp&a\b|valuation|controladoria"),
    "contabil": ("negocios", r"contab|accounting|auditori|\baudit|\bcustos\b|fiscal(?! de (?:obra|campo|loja))|\btax\b"),
    "rh": ("negocios", r"recursos humanos|\brh\b|\bhr\b|human resources|departamento pessoal|\bdp\b|\btalent|\bpeople\b|recrutamento|recruit"),
    "comercial": ("negocios", r"comercial|vendas|\bsales\b|inside sales|key account|account (?:manager|executive)|business development|pre-?vendas"),
    "logistica": ("negocios", r"logistic|supply chain|suprimentos|compras|procurement|purchas|\bpcp\b|planejamento de (?:producao|demanda)|estoque|inventory"),
    "consultoria": ("negocios", r"consult|\bestrategia\b|strategy|business analyst|analista de negocios"),
    "operacoes": ("negocios", r"operac|operations|backoffice|back office|atendimento|customer (?:success|service|experience)|sucesso do cliente"),
    "produto": ("negocios", r"\bproduct (?:manager|owner|management)|gestao de produto|\bproduto\b|product analyst"),
    # Engineering
    "mecanica": ("engenharia", r"mecanic|mechanical|usinagem|\bcad\b|projetos mecanicos"),
    "eletrica": ("engenharia", r"eletric|electrical|eletronic|electronic|automac|automation|eletrotecn|\bpower systems|energia|energy"),
    "civil": ("engenharia", r"engenharia civil|civil engineer|(?<!direito )(?<!processo )\bcivil\b(?! litigation)|\bobras\b|construc|construction|edificac|estrutur"),
    "producao": ("engenharia", r"engenharia de producao|producao|manufatur|manufactur|processos|process engineer|lean|melhoria continua"),
    "quimica_eng": ("engenharia", r"engenharia quimica|chemical engineer|processos quimicos"),
    "qualidade": ("engenharia", r"qualidade|quality"),
    "manutencao": ("engenharia", r"manutencao|maintenance|confiabilidade|reliability"),
    "seguranca_trabalho": ("engenharia", r"seguranca do trabalho|\bsst\b|\behs\b|\bhse\b|saude e seguranca|occupational safety"),
    "minas": ("engenharia", r"\bminas\b(?! gerais)|mineracao|\bmining\b|metalurg|metallurg|geolog|petrole|petroleum"),
    "aeroespacial": ("engenharia", r"aeroespac|aerospace|aeronaut|aircraft|propulsion|avionic"),
    # Computing (besides the tech areas ML, Software, Data...)
    "infra": ("computacao", r"suporte|help ?desk|service desk|infraestrutura|infrastructure|redes\b|networking|\bsysadmin|cloud ops|\bdevops|\bsre\b"),
    "seguranca_info": ("computacao", r"cyber|ciberseg|seguranca da informacao|information security|infosec|security engineer|pentest"),
    "ux": ("computacao", r"\bux\b|\bui\b|user experience|experiencia do usuario|product design"),
    # Communication and marketing
    "marketing": ("comunicacao", r"marketing|growth|\bcrm\b|trade(?! (?:republic|desk|support))|branding|\bmarca\b"),
    "design": ("comunicacao", r"design(?:er)?\b|grafico|graphic|motion|ilustra|artes"),
    "jornalismo": ("comunicacao", r"jornalis|journalis|redac|reporter|conteudo|content|copywrit|editorial"),
    "publicidade": ("comunicacao", r"publicidade|propaganda|advertis|midia|media|social media|redes sociais"),
    "audiovisual": ("comunicacao", r"audiovisual|video|fotograf|photograph|cinema|producao de conteudo"),
    "rp": ("comunicacao", r"relacoes publicas|public relations|comunicacao (?:interna|corporativa|institucional)|assessoria de imprensa"),
    # Biology and agriculture
    "agronomia": ("biologicas", r"agronom|agricol|agricult|agro\b|agronegocio|zootecn|florest|forestry"),
    "biologia": ("biologicas", r"biolog|biotec|biotech|genetica|genetic|microbiolog|bioinformat"),
    "ambiental": ("biologicas", r"ambiental|meio ambiente|environmental|sustentab|sustainab|\besg\b"),
    "alimentos": ("biologicas", r"alimentos|food (?:science|safety|engineer)|engenharia de alimentos"),
    # Education and humanities
    "educacao": ("humanas", r"pedagog|educac(?!ao fisica)|education|ensino (?:fundamental|medio|infantil|de idiomas)|docen|\bprofessor|\bmonitor(?:a|\(a\))?\b|monitoria|tutor|teacher|escola"),
    "letras": ("humanas", r"\bletras\b|tradu[cç]|translat|idiomas|ingles|portugues|linguist"),
    "social": ("humanas", r"servico social|assistente social|social work|ciencias sociais|sociolog"),
    "relacoes_internacionais": ("humanas", r"relacoes internacionais|international relations|comercio exterior|foreign trade"),
    "gestao_publica": ("humanas", r"gestao publica|administracao publica|politicas publicas|public policy|setor publico"),
    "historia": ("humanas", r"historia|geografia|filosofia|arqueolog|museu|museum"),
    # Architecture
    "arquitetura": ("arquitetura", r"arquitet(?!ura (?:de software|de dados|de solucoes|cloud|corporativa|enterprise))|architect(?!ure)(?! software)"),
    "urbanismo": ("arquitetura", r"urbanis|urban planning|paisagis|landscape"),
    "interiores": ("arquitetura", r"interiores|interior design"),
    # Sciences
    "estatistica": ("exatas", r"estatistic|statistic|atuari|actuar"),
    "matematica": ("exatas", r"matematic|mathemat"),
    "fisica": ("exatas", r"(?<!educacao )\bfisica\b|\bphysics\b"),
    "quimica": ("exatas", r"\bquimica\b|\bchemistry\b|\bchemist\b"),
}
_COMPILED = {key: re.compile(pattern) for key, (_, pattern) in SUBAREAS.items()}
SECTIONS = {key: section for key, (section, _) in SUBAREAS.items()}


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def find_subareas(title: str) -> list[str]:
    """Sub-area keys named in a title, in the order of SUBAREAS; [] when none."""
    text = _plain(title)
    return [key for key, pattern in _COMPILED.items() if pattern.search(text)][:4]
