"""Role families, skill vocabulary, seniority ladder.

This file is the product's brain. Everything downstream (matching, scoring,
digest relevance) is only as good as these patterns. Spend your first real
week here, iterating against actual recruiter feedback.

Rules of thumb encoded below:
  * Word-boundary regex only. Substring matching gives you "java" inside
    "javascript", which is the classic false positive.
  * Order matters within a family: put specific patterns before generic ones.
  * Negative patterns exist because titles lie ("Sales Engineer" is not
    engineering, "Solutions Architect" usually isn't either).
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------
# canonical -> regex alternation (matched case-insensitively with word bounds)
SKILL_PATTERNS: dict[str, str] = {
    # languages
    "python": r"python|py3|python3",
    "java": r"\bjava\b(?!script)",
    "javascript": r"javascript|\bjs\b|ecmascript",
    "typescript": r"typescript|\bts\b",
    "go": r"\bgolang\b|\bgo\b(?=\s*(?:dev|developer|engineer|lang))",
    "rust": r"\brust\b",
    "ruby": r"\bruby\b|rails",
    "php": r"\bphp\b|laravel|symfony",
    "csharp": r"c#|c-sharp|csharp|\.net\b|dotnet|asp\.net",
    "cpp": r"c\+\+|cpp",
    "c": r"(?<![\w+#])c(?![\w+#])(?=\s*(?:dev|developer|engineer|lang|programmer))",
    "kotlin": r"\bkotlin\b",
    "swift": r"\bswift\b",
    "scala": r"\bscala\b",
    "elixir": r"\belixir\b|phoenix framework",
    "erlang": r"\berlang\b",
    "haskell": r"\bhaskell\b",
    "r_lang": r"\br\b(?=\s*(?:programming|developer|analyst|stats))",
    "matlab": r"\bmatlab\b",
    "perl": r"\bperl\b",
    "sql": r"\bsql\b",
    "bash": r"\bbash\b|shell scripting",
    "solidity": r"\bsolidity\b",
    # frontend
    "react": r"\breact(?:\.js|js)?\b",
    "nextjs": r"\bnext\.?js\b",
    "angular": r"\bangular(?:js)?\b",
    "vue": r"\bvue(?:\.js|js)?\b",
    "svelte": r"\bsvelte(?:kit)?\b",
    "redux": r"\bredux\b",
    "tailwind": r"\btailwind\b",
    "sass": r"\bsass\b|\bscss\b",
    "webpack": r"\bwebpack\b|\bvite\b",
    "html_css": r"\bhtml5?\b|\bcss3?\b",
    "accessibility": r"\ba11y\b|accessibility|wcag",
    # backend / frameworks
    "nodejs": r"\bnode(?:\.js|js)?\b",
    "django": r"\bdjango\b",
    "flask": r"\bflask\b",
    "fastapi": r"\bfastapi\b",
    "spring": r"\bspring(?:\s*boot)?\b",
    "hibernate": r"\bhibernate\b",
    "express": r"\bexpress(?:\.js|js)?\b",
    "rails": r"\brails\b|ruby on rails",
    "laravel": r"\blaravel\b",
    "graphql": r"\bgraphql\b",
    "grpc": r"\bgrpc\b",
    "rest_api": r"\brest(?:ful)?\b|\bapi design\b",
    "microservices": r"micro-?services?",
    "kafka": r"\bkafka\b",
    "rabbitmq": r"\brabbitmq\b",
    "celery": r"\bcelery\b",
    # data stores
    "postgres": r"postgres(?:ql)?",
    "mysql": r"\bmysql\b|mariadb",
    "mongodb": r"\bmongo(?:db)?\b",
    "redis": r"\bredis\b",
    "elasticsearch": r"\belasticsearch\b|\belastic search\b|\bopensearch\b",
    "cassandra": r"\bcassandra\b",
    "dynamodb": r"\bdynamodb\b",
    "snowflake": r"\bsnowflake\b",
    "bigquery": r"\bbigquery\b",
    "redshift": r"\bredshift\b",
    "databricks": r"\bdatabricks\b",
    "clickhouse": r"\bclickhouse\b",
    # data engineering
    "spark": r"\bspark\b|pyspark",
    "hadoop": r"\bhadoop\b",
    "airflow": r"\bairflow\b",
    "dbt": r"\bdbt\b",
    "etl": r"\betl\b|\belt\b|data pipeline",
    "pandas": r"\bpandas\b",
    "numpy": r"\bnumpy\b",
    # cloud / infra
    "aws": r"\baws\b|amazon web services",
    "azure": r"\bazure\b",
    "gcp": r"\bgcp\b|google cloud",
    "kubernetes": r"\bkubernetes\b|\bk8s\b",
    "docker": r"\bdocker\b|containerization",
    "terraform": r"\bterraform\b",
    "pulumi": r"\bpulumi\b",
    "ansible": r"\bansible\b",
    "helm": r"\bhelm\b",
    "istio": r"\bistio\b|service mesh",
    "linux": r"\blinux\b|\bunix\b",
    "serverless": r"\bserverless\b|\blambda\b",
    # ci/cd & observability
    "cicd": r"\bci/?cd\b|continuous integration|continuous delivery",
    "jenkins": r"\bjenkins\b",
    "gitlab_ci": r"\bgitlab\b",
    "github_actions": r"github actions",
    "circleci": r"\bcircleci\b",
    "argocd": r"\bargo ?cd\b",
    "prometheus": r"\bprometheus\b",
    "grafana": r"\bgrafana\b",
    "datadog": r"\bdatadog\b",
    "observability": r"\bobservability\b|\bopentelemetry\b|\botel\b",
    # ml / ai
    "tensorflow": r"\btensorflow\b",
    "pytorch": r"\bpytorch\b|\btorch\b",
    "sklearn": r"\bscikit-?learn\b|\bsklearn\b",
    "mlops": r"\bmlops\b|\bmlflow\b|\bkubeflow\b",
    "llm": r"\bllms?\b|large language model|\bgenai\b|generative ai",
    "rag": r"\brag\b|retrieval[- ]augmented",
    "langchain": r"\blangchain\b|\bllamaindex\b",
    "nlp": r"\bnlp\b|natural language",
    "computer_vision": r"computer vision|\bopencv\b",
    "recommender": r"recommend(?:er|ation) system",
    # mobile
    "ios": r"\bios\b|swiftui|uikit",
    "android": r"\bandroid\b|jetpack compose",
    "react_native": r"react native",
    "flutter": r"\bflutter\b|\bdart\b",
    # qa
    "selenium": r"\bselenium\b",
    "cypress": r"\bcypress\b",
    "playwright": r"\bplaywright\b",
    "pytest": r"\bpytest\b",
    "junit": r"\bjunit\b",
    "automation_testing": r"test automation|automated testing|\bsdet\b",
    "manual_qa": r"manual qa|manual testing",
    # security
    "appsec": r"\bappsec\b|application security",
    "pentest": r"pen(?:etration)? ?test|offensive security|red team",
    "soc": r"\bsoc\b|security operations",
    "siem": r"\bsiem\b|splunk|sentinel",
    "iam": r"\biam\b|identity and access|oauth|saml|okta",
    "cloud_security": r"cloud security|cloud security posture|\bcspm\b",
    "grc": r"\bgrc\b|governance risk|iso 27001|soc ?2",
    "threat_intel": r"threat intel",
    # enterprise / ERP
    "salesforce": r"\bsalesforce\b|\bapex\b|\blwc\b",
    "servicenow": r"\bservicenow\b",
    "workday": r"\bworkday\b",
    "sap": r"\bsap\b(?!\s*successfactors?)|\bs4 ?hana\b|\babap\b",
    "oracle_erp": r"oracle (?:erp|fusion|ebs|hcm)",
    "dynamics": r"dynamics ?365|\bmsdyn\b",
    "pega": r"\bpega\b",
    "mulesoft": r"\bmulesoft\b|\bboomi\b|\binformatica\b|\btalend\b",
    # analytics / bi
    "tableau": r"\btableau\b",
    "powerbi": r"power ?bi",
    "looker": r"\blooker\b|\blookml\b",
    "qlik": r"\bqlik\b",
    # product / design
    "figma": r"\bfigma\b|\bsketch\b",
    "product_analytics": r"\bamplitude\b|\bmixpanel\b|\bsegment\b",
}

_SKILL_RE = {k: re.compile(rf"(?<![\w#+.]){v}(?![\w#+.])", re.IGNORECASE) for k, v in SKILL_PATTERNS.items()}

# --------------------------------------------------------------------------
# Role families
# --------------------------------------------------------------------------
ROLE_FAMILIES: dict[str, str] = {
    "security": (
        r"security engineer|security analyst|appsec|application security|"
        r"penetration test|pentester|red team|blue team|soc analyst|"
        r"security architect|infosec|information security|cissp|"
        r"threat|vulnerability|incident response|devsecops|grc analyst|"
        r"security operations|cyber"
    ),
    "sre": r"\bsre\b|site reliability|reliability engineer|production engineer",
    "devops": (
        r"devops|dev ops|platform engineer|infrastructure engineer|cloud engineer|"
        r"build and release|release engineer|systems engineer|"
        r"kubernetes engineer|automation engineer"
    ),
    "ml": (
        r"machine learning|ml engineer|\bmlops\b|deep learning|"
        r"ai engineer|artificial intelligence|nlp engineer|"
        r"computer vision engineer|research scientist|applied scientist|"
        r"llm engineer|genai engineer|ai research"
    ),
    "data_science": r"data scientist|decision scientist|quantitative analyst|statistician",
    "data_engineering": (
        r"data engineer|analytics engineer|etl developer|data architect|"
        r"big data engineer|data platform|database engineer|\bdba\b|"
        r"database administrator"
    ),
    "analytics": r"data analyst|business analyst|bi analyst|analytics engineer|product analyst",
    "mobile": r"ios (?:engineer|developer)|android (?:engineer|developer)|mobile (?:engineer|developer)|react native|flutter developer",
    "frontend": (
        r"front[- ]end|frontend|ui engineer|ui developer|web developer|"
        r"react (?:engineer|developer)|angular (?:engineer|developer)|"
        r"vue (?:engineer|developer)|javascript engineer"
    ),
    "fullstack": r"full[- ]?stack",
    "backend": (
        r"back[- ]end|backend|server[- ]side|api engineer|api developer|"
        r"software engineer|software developer|application developer|"
        r"programmer analyst|member of technical staff|\bsde\b|\bswe\b"
    ),
    "embedded": r"embedded|firmware|\brtos\b|fpga|hardware engineer|electrical engineer",
    "qa": r"\bqa\b|quality assurance|test engineer|sdet|automation engineer.*test|tester",
    "network": r"network engineer|network architect|noc engineer|telecom engineer",
    "erp": (
        r"salesforce|servicenow|workday|sap (?:consultant|developer|analyst)|"
        r"oracle (?:erp|fusion|hcm)|dynamics 365|pega|mulesoft|"
        r"netsuite|sage (?:developer|consultant)"
    ),
    "product": r"product manager|product owner|technical product|\bpm\b(?!\s*shift)|program manager",
    "design": r"\bux\b|\bui/?ux\b|product designer|interaction designer|visual designer|user researcher",
    "management": r"engineering manager|director of engineering|\bvp\b.*engineering|\bcto\b|head of engineering|tech lead",
    "support": r"support engineer|technical support|customer engineer|solutions engineer|sales engineer|field engineer",
}

# Evaluated first: if a title matches, it is rejected outright.
NEGATIVE_TITLE_PATTERNS = re.compile(
    r"\b(?:sales|account executive|account manager|recruiter|talent|"
    r"marketing|content writer|copywriter|seo|hr |human resources|"
    r"customer success|business development|finance|accountant|"
    r"legal|counsel|office manager|administrative|executive assistant)\b",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------
# Seniority
# --------------------------------------------------------------------------
SENIORITY_PATTERNS: list[tuple[str, str]] = [
    ("intern", r"\bintern\b|\binternship\b|\bco-?op\b|\btrainee\b|\bapprentice\b"),
    ("principal", r"\bprincipal\b|\bstaff\b|\bfellow\b|\bdistinguished\b|\barchitect\b"),
    ("director", r"\bdirector\b|\bvp\b|\bvice president\b|\bhead of\b|\bchief\b|\bcto\b|\bcio\b|\bciso\b"),
    ("manager", r"\bmanager\b|\blead\b|\bsupervisor\b|\bhead\b"),
    ("senior", r"\bsenior\b|\bsr\.?\b|\blead\b|\biii\b|\biv\b"),
    ("junior", r"\bjunior\b|\bjr\.?\b|\bentry[- ]level\b|\bgraduate\b|\bassociate\b|\bi\b"),
    ("mid", r"\bmid[- ]level\b|\bii\b|\bintermediate\b"),
]

_SENIORITY_RE = [(name, re.compile(p, re.IGNORECASE)) for name, p in SENIORITY_PATTERNS]

SENIORITY_ORDER = ["intern", "junior", "mid", "senior", "principal", "manager", "director"]

# --------------------------------------------------------------------------
# Location
# --------------------------------------------------------------------------
REMOTE_PATTERNS = [
    (re.compile(r"\bfully remote\b|\b100% remote\b|\bremote[- ]first\b|\bwork from anywhere\b|\banywhere\b", re.I), "remote"),
    (re.compile(r"\bhybrid\b|\b\d+\s*days?\s*(?:per week\s*)?(?:in|on)[- ]?site\b", re.I), "hybrid"),
    (re.compile(r"\bremote\b|\bwfh\b|\btelecommut", re.I), "remote"),
    (re.compile(r"\bon[- ]?site\b|\bin[- ]office\b|\bin person\b", re.I), "onsite"),
]

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "district of columbia": "DC", "washington dc": "DC", "washington, d.c.": "DC",
}
US_STATE_CODES = set(US_STATES.values())

COUNTRY_ALIASES: dict[str, str] = {
    "united states": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US", "us": "US",
    "united kingdom": "GB", "uk": "GB", "u.k.": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "great britain": "GB",
    "canada": "CA", "germany": "DE", "deutschland": "DE", "france": "FR",
    "netherlands": "NL", "holland": "NL", "spain": "ES", "españa": "ES",
    "italy": "IT", "portugal": "PT", "ireland": "IE", "poland": "PL", "polska": "PL",
    "sweden": "SE", "norway": "NO", "denmark": "DK", "finland": "FI", "switzerland": "CH",
    "austria": "AT", "belgium": "BE", "czech republic": "CZ", "czechia": "CZ",
    "romania": "RO", "ukraine": "UA", "hungary": "HU", "greece": "GR", "turkey": "TR",
    "israel": "IL", "india": "IN", "china": "CN", "japan": "JP", "south korea": "KR",
    "korea": "KR", "singapore": "SG", "australia": "AU", "new zealand": "NZ",
    "brazil": "BR", "mexico": "MX", "argentina": "AR", "chile": "CL", "colombia": "CO",
    "peru": "PE", "costa rica": "CR", "south africa": "ZA", "nigeria": "NG",
    "kenya": "KE", "egypt": "EG", "uae": "AE", "united arab emirates": "AE",
    "saudi arabia": "SA", "philippines": "PH", "vietnam": "VN", "thailand": "TH",
    "indonesia": "ID", "malaysia": "MY", "pakistan": "PK", "bangladesh": "BD",
    "russia": "RU", "bulgaria": "BG", "croatia": "HR", "serbia": "RS", "slovakia": "SK",
    "slovenia": "SI", "lithuania": "LT", "latvia": "LV", "estonia": "EE",
}

HEADCOUNT_BANDS = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5000+"]
