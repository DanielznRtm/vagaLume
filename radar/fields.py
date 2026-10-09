"""Which fields of study a posting is aimed at (engineering, law, health...).

The website asks students for their field and hides roles clearly meant for
other fields (they can show them again with one click). Roles that don't say
which field they want are always shown.

Fields come from the title first. If the title names no field (e.g.
"Estagiário(a)"), we look at the course phrases in the description
("cursando Direito ou Administração", "graduação em Engenharia", "degree in
Computer Science", up to the end of that sentence), not the whole text,
because company blurbs and activity lists mention everything. Patterns are matched without accents, in Portuguese and English.

The site keeps its own list of which fields are related (an engineering
student also sees computing roles), see FIELD_RELATED in docs/index.html.
"""

from __future__ import annotations

import re
import unicodedata

FIELDS: dict[str, str] = {
    "engenharia": r"\bengenh|\bengineer|mecanic|\bmechanical|eletric|\belectrical|eletronic|\belectronic|automacao|\bautomation|mecatronic|mechatronic"
                  r"|\bcivil\b|engenharia de producao|manufatur|manufactur|\bhardware|firmware|\bembedded|embarcad|robotic|aeroespac|aerospace|\bnaval\b"
                  r"|metalurg|metallurg|\bpetroleo|petroleum|mineracao|\bmining\b|eletrotecnic|manutencao|\bmaintenance|telecomunica|telecom\b|\bsolidworks|\bautocad|seguranca do trabalho|occupational safety|cartograf|edificacoes|agrimensura",
    "computacao": r"comput|informatica|sistemas para internet|implantacao de sistemas|\bsoftware|desenvolv|developer|programad|programming|\bti\b|tecnologia da informacao|information technology|sistemas de informacao"
                  r"|analise e desenvolvimento de sistemas|\bdata\b|\bdados\b|machine learning|aprendizado de maquina|inteligencia artificial|artificial intelligence"
                  r"|\bai\b|\bia\b|\bml\b|\bcyber|seguranca da informacao|\bdevops|\bcloud\b|front[ -]?end|back[ -]?end|full[ -]?stack|\bweb\b|\bmobile\b"
                  r"|\bandroid\b|\bios\b|\bqa\b|quality assurance|suporte tecnico|help ?desk|infraestrutura de ti|redes de computadores"
                  r"|arquitetura (?:enterprise|de software|de dados|de solucoes|cloud|corporativa)|software architect",
    "exatas": r"matematic|mathemat|estatistic|statistic|(?<!educacao )\bfisica\b|\bphysics\b|\bquimica\b|\bchemistry|atuari|actuar|\bquant\b|quantitative",
    "negocios": r"administra|\bbusiness|economi|contab|accounting|financ|controladoria|\bfiscal|tribut|\baudit|comercial|\bvendas|\bsales\b|\bcompras"
                r"|procurement|suprimentos|logistic|supply chain|recursos humanos|\brh\b|human resources|\bpeople\b|\btalent|atendimento|customer (service|success)"
                r"|relacionamento|bancari|\bbanking|investiment|investment|\bcredito|\bcredit\b|\bseguros|operacoes|\boperations|planejamento|\bgestao"
                r"|secretari|consultor|consulting|estrategi|strategy|\bproduto\b|\bproduct\b|trading|\bmercado financeiro"
                r"|account management|account executive|key account|\bmarketplace|vended|governanca",
    "direito": r"\bdireito|juridic|\blegal\b|\blaw\b|advoca|paralegal|\bcompliance|contencioso",
    "saude": r"enfermag|nursing|\bnurse|medicin|\bmedical|farmac|pharmac|\bnutri|psicolog|psycholog|fisioterap|physiotherap|odontolog|dentist|biomedic"
             r"|veterinar|terapia ocupacional|fonoaudiolog|radiolog|\bclinic|hospital|\bsaude\b|health ?care|educacao fisica|\besporte"
             r"|natacao|crossfit|musculacao|recreacao|alongamento|pilates|personal trainer",
    "biologicas": r"\bbiolog|biotec|biotech|agronom|agricult|\bagro|zootec|florest|\bforest|ambient|environment|sustentab|sustainab|ecolog|geolog"
                  r"|geocien|oceanograf|engenharia de alimentos|ciencia de alimentos|food science|bioquim|biochem|genetic|microbio",
    "comunicacao": r"comunica|communication|jornalis|journalis|marketing|publicidade|propaganda|advertising|relacoes publicas|public relations"
                   r"|designer|design (?:grafico|de produto|visual|digital|de moda|de interiores|instrucional)|(?:graphic|visual|product|web|ux|ui) design"
                   r"|\bartes (?:visuais|plasticas|cenicas)|\bmusica\b|\bux\b|\bui\b|grafic|graphic|midias? sociais|social media|redator|redacao|copywrit|\bconteudo|\bcontent\b|audiovisual|\bvideo"
                   r"|fotograf|cinema|\beventos|branding|\bcriacao|creative",
    "humanas": r"pedagog|\beducacao\b(?! fisica)|\beducation\b|\bensino\b|professor|teacher|letras|idiomas|\blanguages?\b|traduc|translat|\bhistoria\b|\bhistory\b"
               r"|geografia|sociolog|antropolog|filosofi|ciencias sociais|social sciences|servico social|social work|relacoes internacionais"
               r"|international relations|turismo|tourism|hotelaria|gastronomia|biblioteconom|museolog|arquivolog",
    "arquitetura": r"arquitetura e urbanismo|urbanis|paisagis|design de interiores|architectural|arquitet[ao]s?\b(?! (de |da |do |enterprise|cloud|corporativ))",
}
_COMPILED = {name: re.compile(pattern) for name, pattern in FIELDS.items()}
NAMES = list(FIELDS)

# Phrases that introduce the courses a posting accepts.
_COURSE_PHRASE = re.compile(
    r"(?:cursando|graduacao em|graduandos? (?:em|de)|estudantes? (?:de|do curso de)|formacao em|cursos?:|cursos? de|area:|"
    r"students? (?:of|in|majoring in|pursuing)|degree in|majoring in|pursuing a (?:bachelor'?s|master'?s|degree) (?:degree )?in)([^.;\n]{0,80})"
)


def _plain(text: str) -> str:
    """Lower case without accents: "Administração" -> "administracao"."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _match(text: str) -> list[str]:
    return [name for name, pattern in _COMPILED.items() if pattern.search(text)]


def find_fields(title: str, description: str = "") -> list[str]:
    """The fields a posting is aimed at, in the order of FIELDS; [] = it doesn't say."""
    found = _match(_plain(title))
    if found:
        return found
    courses = " ".join(m.group(1) for m in _COURSE_PHRASE.finditer(_plain(description)))
    return _match(courses)
