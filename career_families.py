"""Target career families with title aliases and responsibility signals."""
import re

# Each description pattern requires a specific responsibility or workflow.
FAMILIES = (
    ("Business Operations", r"business ops|business operations?|bizops|operations (?:manager|coordinator|analyst|specialist|associate|lead)|operational excellence|operations program manager",
     r"(?:run|improve|scale|manage|optimise|optimize).{0,45}(?:business operations|operating processes|operational workflows)|cross.functional operating cadence"),
    ("Commercial Operations", r"commercial ops|commercial operations?|commercial (?:analyst|excellence|manager)|go.to.market operations",
     r"commercial performance reporting|commercial operating model|manage commercial processes|support commercial execution"),
    ("International Business Development", r"international (?:business development|sales|commercial development|business manager)|global business development|export development|international growth|international account executive|export sales",
     r"(?:develop|grow|expand|build).{0,45}(?:cross.border business|international sales|international partnerships|export markets)"),
    ("Strategic Partnerships", r"(?:strategic |channel |commercial |ecosystem |alliances? )?partnerships?|partner (?:manager|management|development|enablement)|alliances? (?:manager|lead)",
     r"(?:build|manage|develop|negotiate|grow|launch).{0,38}(?:strategic partnerships|channel partnerships|partner ecosystem|partner programs|commercial alliances)"),
    ("Market Expansion / Market Entry", r"market (?:expansion|entry|development)|international expansion|new markets lead|new market launch|market launch (?:associate|manager|lead)|market intelligence (?:analyst|manager)|country launch|expansion (?:manager|lead)",
     r"(?:enter|launch|expand into|evaluate).{0,35}(?:new markets|international markets|new geographies)|market entry strateg"),
    ("Project Operations / Project Coordinator", r"project (?:operations?|coordinator|coordination|manager|specialist|officer|analyst)|program(?:me)? (?:coordinator|manager)|PMO (?:coordinator|analyst|manager)|implementation (?:manager|coordinator|specialist)",
     r"(?:coordinate|track|manage).{0,36}(?:project milestones|project schedules|program delivery|project deliverables|project governance)|creative project management|manage scope.{0,40}feedback loops"),
    ("Business Development Manager", r"business development|BDM|sales development|account executive|commercial growth (?:manager|lead)|new business (?:manager|development)",
     r"(?:identify|develop|build|qualify|convert).{0,45}(?:new business opportunities|sales pipeline|commercial pipeline|qualified prospects)|win new clients"),
    ("Client Relationship Manager", r"client (?:relations?(?:hip)?|services?|success|experience|manager)|customer success|relationship manager|account services",
     r"(?:manage|build|retain|strengthen).{0,45}(?:client relationships|customer relationships|client accounts)|client onboarding and retention"),
    ("Commercial Project Management", r"commercial project (?:management|manager|lead)|commercial program(?:me)? manager|commercial delivery (?:manager|lead)|commercial transformation (?:manager|lead)|client delivery manager|contract project manager",
     r"(?:manage|lead|deliver|coordinate).{0,35}(?:commercial projects|commercial program(?:me)?s|client funded projects|contract delivery milestones)"),
    ("Sales Operations / Revenue Operations", r"sales (?:ops|operations?|planning|enablement|effectiveness)|revenue (?:ops|operations?|enablement)|revops|sales performance analyst|revenue enablement|deal desk (?:analyst|specialist|manager)",
     r"sales forecasting and pipeline|sales operations processes|revenue operations|maintain.{0,30}(?:sales dashboards|sales forecasts|CRM data quality)"),
    ("Vendor / Supplier Management", r"(?:vendor|supplier) (?:management|manager|development|relations?|performance)|supplier development manager|vendor relationship|procurement (?:manager|coordinator|specialist)|strategic sourcing",
     r"(?:manage|select|onboard|evaluate|monitor).{0,35}(?:supplier performance|vendor performance|supplier relationships|vendors|suppliers)|supplier selection"),
    ("Business Strategy & Planning", r"business (?:strategy|planning)|strategic planning|corporate strategy|strategy and planning|commercial strategy|strategic initiatives",
     r"(?:develop|define|lead|execute).{0,36}(?:business strategy|annual operating plan|strategic planning|commercial strategy|strategic roadmap)"),
    ("Chief of Staff Associate / Executive Operations", r"chief of staff|executive operations|office of the CEO|executive business partner|executive strategy associate|strategic executive assistant",
     r"(?:support|advise|coordinate).{0,36}(?:executive leadership|CEO priorities|executive operating rhythm)|chief of staff"),
    ("Account Management / Key Account Management", r"(?:key |strategic |national |global |enterprise )?account (?:management|manager|lead|director)|customer account manager|KAM",
     r"(?:manage|grow|retain|own).{0,40}(?:key accounts|strategic accounts|account portfolio|enterprise accounts)|account plans and renewals"),
    ("Trade Operations / Trade Support", r"trade (?:operations?|support|processing|settlement|finance operations)|trading operations?|trade lifecycle|middle office|trading support|trading application support|brokerage operations",
     r"(?:reconcile|confirm|settle|process|capture).{0,35}(?:trades|trade transactions)|trade lifecycle|trade settlements"),
    ("Commodity Commercial Operations", r"commodit(?:y|ies) (?:commercial|trading|operations?|analyst)|(?:energy|oil|gas|metals|agricultural|power|lng) (?:commercial|trading|trade operations)|commercial manager.{0,18}energy",
     r"commodity contracts|physical commodity trading|(?:manage|coordinate).{0,36}(?:crude oil|commodity logistics|energy trading contracts)"),
    ("Investment Operations / Deal Coordination", r"investment (?:operations?|support|associate)|deal (?:operations?|coordinator|coordination|execution|support)|investment operations analyst|transaction services associate|portfolio operations|transaction (?:operations?|coordinator)|fund operations",
     r"(?:coordinate|support|manage).{0,35}(?:investment due diligence|deal execution|investment transactions|investment operations)|investment transaction documentation"),
    ("Business Analyst", r"business analyst|business analysis|business process analyst|commercial business analyst|business systems analyst",
     r"(?:gather|document|analyse|analyze).{0,35}(?:business requirements|business processes)|process mapping and requirements"),
    ("Shipping / Logistics Operations", r"shipping|logistics|supply chain operations?|freight (?:operations?|coordinator)|vessel operations?|transport(?:ation)? operations?|fulfil(?:l)?ment operations",
     r"(?:coordinate|manage|plan|schedule).{0,35}(?:shipments|freight|vessel schedules|logistics operations|order fulfillment|order fulfilment)|supply chain coordination"),
    ("Strategy & Operations Consulting", r"strategy (?:&|and) operations|strategic consulting|(?:management|operations|strategy|business transformation) consult(?:ant|ing)|business advisory",
     r"client advisory engagements|(?:advise|consult).{0,40}(?:operating model|operational transformation|business strategy)|deliver strategy consulting"),
)

_NAMES = [name for name, _, _ in FAMILIES]
PATTERNS = [(name, re.compile(rf"\b(?:{title})\b", re.I), re.compile(rf"\b(?:{duties})", re.I))
            for name, title, duties in FAMILIES]


def names():
    return list(_NAMES)


def classify_roles(title, jd):
    title = " ".join(title.split())
    duties = []
    in_section = False
    if jd and not jd.startswith("[Partial JD]"):
        for line in re.split(r"\n+|(?<=[.!?])\s+", jd):
            line = line.strip(" •-")
            if not line:
                continue
            if re.match(r"^(?:required|preferred|qualifications|requirements|what you bring|what we offer|benefits|compensation|about us|you have)\b", line, re.I):
                in_section = False
            elif re.search(r"\b(?:responsibilities|what you(?:'ll| will) do|core activities|what you will be doing)\b", line, re.I):
                in_section = True
            elif in_section or re.match(r"^(?:lead|manage|support|own|coordinate|develop|build|execute|oversee|identify|conduct|collaborate|partner|optimis[ez]|analyse|analyze|plan|drive)\b", line, re.I):
                duties.append(line)
    return [name for name, title_pattern, duty_pattern in PATTERNS
            if title_pattern.search(title) or any(duty_pattern.search(line) for line in duties)]
