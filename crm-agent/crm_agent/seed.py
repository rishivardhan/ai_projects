"""Step 2 - Dummy data.

Generates a realistic, internally consistent CRM dataset for a fictional SaaS
vendor ("Northwind Cloud") that sells a data platform to other companies.

Everything is deterministic (fixed RNG seed); dates are relative to the day the
seed runs, so "closing this month" and "last 30 days" questions stay meaningful.

    python -m crm_agent.seed            # seed if empty
    python -m crm_agent.seed --reset    # wipe and re-seed
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta

SEED = 42

REPS = ["Priya Shah", "Marcus Lee", "Elena Rossi", "David Okafor", "Hannah Kim"]

PRODUCTS = {
    "Core Platform": 48000,
    "Analytics Add-on": 18000,
    "AI Assist": 24000,
    "Data Connectors Pack": 9000,
    "Premium Support": 12000,
}

STAGES = [  # (stage, default win probability)
    ("Prospecting", 10),
    ("Qualification", 20),
    ("Proposal", 50),
    ("Negotiation", 75),
    ("Closed Won", 100),
    ("Closed Lost", 0),
]
OPEN_STAGES = ["Prospecting", "Qualification", "Proposal", "Negotiation"]
CLOSE_WINDOW = {  # days from today
    "Prospecting": (45, 150), "Qualification": (25, 110), "Proposal": (5, 80),
    "Negotiation": (-12, 45), "Closed Won": (-150, -5), "Closed Lost": (-150, -5),
}
NEXT_STEPS = {
    "Prospecting": ["Book discovery call", "Send intro deck to VP of Data", "Research org chart"],
    "Qualification": ["Schedule technical deep-dive", "Confirm economic buyer", "Map decision process"],
    "Proposal": ["Send revised pricing", "Security review", "Pilot success review"],
    "Negotiation": ["Legal redlines on MSA", "Executive sponsor meeting", "Final pricing approval"],
}

ACCOUNTS = [
    # name, industry, region, country, city, employees
    ("Acme Logistics", "Logistics", "NA", "USA", "Chicago", 4200),
    ("Globex Financial", "Financial Services", "NA", "USA", "New York", 12000),
    ("Initech Software", "Technology", "NA", "USA", "Austin", 850),
    ("Umbrella Health", "Healthcare", "NA", "USA", "Boston", 9600),
    ("Stark Manufacturing", "Manufacturing", "NA", "USA", "Detroit", 15000),
    ("Wayne Retail Group", "Retail", "NA", "USA", "Seattle", 22000),
    ("Hooli Media", "Media", "NA", "USA", "San Francisco", 3100),
    ("Pied Piper Data", "Technology", "NA", "USA", "Palo Alto", 140),
    ("Vandelay Imports", "Wholesale", "NA", "USA", "Newark", 380),
    ("Tyrell Biotech", "Life Sciences", "NA", "Canada", "Toronto", 2700),
    ("Oceanic Airlines", "Travel", "APAC", "Australia", "Sydney", 18000),
    ("Soylent Foods", "Consumer Goods", "EMEA", "Netherlands", "Amsterdam", 5400),
    ("Cyberdyne Systems", "Technology", "NA", "USA", "Sunnyvale", 7200),
    ("Gringotts Bank", "Financial Services", "EMEA", "UK", "London", 26000),
    ("Monarch Insurance", "Insurance", "EMEA", "Germany", "Munich", 8100),
    ("Nakatomi Trading", "Wholesale", "APAC", "Japan", "Tokyo", 6400),
    ("Massive Dynamic", "Manufacturing", "NA", "USA", "Denver", 11000),
    ("Blue Sun Energy", "Energy", "APAC", "Singapore", "Singapore", 4900),
    ("Aperture Labs", "Life Sciences", "NA", "USA", "Cleveland", 1600),
    ("Wonka Confections", "Consumer Goods", "EMEA", "UK", "Manchester", 2300),
    ("Dunder Paper Co", "Wholesale", "NA", "USA", "Scranton", 450),
    ("Sterling Cooper Agency", "Media", "NA", "USA", "New York", 620),
    ("Prestige Worldwide", "Travel", "EMEA", "France", "Paris", 980),
    ("Rekall Telecom", "Telecommunications", "EMEA", "Spain", "Madrid", 14500),
    ("Zenith Utilities", "Energy", "NA", "USA", "Phoenix", 7800),
]

FIRST = ["Olivia", "Liam", "Emma", "Noah", "Ava", "James", "Sophia", "Lucas", "Mia", "Ethan",
         "Isabella", "Mateo", "Amara", "Kenji", "Fatima", "Rahul", "Chloe", "Diego", "Zara",
         "Tomas", "Ingrid", "Wei", "Nadia", "Samuel", "Leila", "Oscar", "Yuki", "Grace"]
LAST = ["Johnson", "Patel", "Garcia", "Chen", "Müller", "Okoye", "Silva", "Nguyen", "Brown",
        "Kowalski", "Haddad", "Tanaka", "Andersson", "Moreau", "Rossi", "Kaur", "Walsh",
        "Fischer", "Novak", "Reyes", "Ibrahim", "Larsen", "Dubois", "Cohen"]

ROLES = [  # title, department, seniority
    ("Chief Technology Officer", "Engineering", "C-Level"),
    ("Chief Financial Officer", "Finance", "C-Level"),
    ("VP of Data", "Data & Analytics", "VP"),
    ("VP of Operations", "Operations", "VP"),
    ("Director of IT", "IT", "Director"),
    ("Head of Procurement", "Procurement", "Director"),
    ("Data Engineering Manager", "Data & Analytics", "Manager"),
    ("Security Architect", "IT Security", "Individual Contributor"),
    ("Senior Data Analyst", "Data & Analytics", "Individual Contributor"),
    ("Product Manager", "Product", "Manager"),
]

COMPETITORS = ["Snowflake", "Databricks", "an in-house Hadoop stack", "Tableau", "Domo"]

LEAD_COMPANIES = [
    ("Bluth Development", "Real Estate"), ("Kramerica Industries", "Consumer Goods"),
    ("Los Pollos Holdings", "Retail"), ("Wernham Hogg", "Wholesale"),
    ("Spacely Sprockets", "Manufacturing"), ("Cogswell Cogs", "Manufacturing"),
    ("Krusty Krab Holdings", "Retail"), ("Duff Beverages", "Consumer Goods"),
    ("InGen Research", "Life Sciences"), ("Weyland Corp", "Technology"),
    ("Ollivanders Ltd", "Retail"), ("Planet Express", "Logistics"),
    ("Buy n Large", "Retail"), ("Virtucon", "Technology"),
    ("Gekko & Co", "Financial Services"), ("Nimbus Insurance", "Insurance"),
    ("Paper Street Soap", "Consumer Goods"), ("Oscorp Labs", "Life Sciences"),
    ("Daily Planet Media", "Media"), ("Union Aerospace", "Manufacturing"),
    ("Callisto Freight", "Logistics"), ("Ghostwood Timber", "Energy"),
    ("Mooby's Restaurants", "Retail"), ("Benthic Petroleum", "Energy"),
    ("Contoso Pharma", "Life Sciences"), ("Fabrikam Telecom", "Telecommunications"),
    ("Litware Analytics", "Technology"), ("Tailspin Toys", "Consumer Goods"),
    ("Woodgrove Bank", "Financial Services"), ("Adventure Works Travel", "Travel"),
]
LEAD_SOURCES = ["Web Form", "Referral", "Trade Show", "Outbound", "Partner", "Webinar"]
LEAD_INTERESTS = ["Real-time analytics", "Replacing legacy BI", "AI-assisted reporting",
                  "Data warehouse migration", "Customer 360 dashboards", "Cost reduction"]

# Note templates per interaction type. Placeholders are filled from context.
NOTE_TEMPLATES = {
    "Call": [
        "Discovery call with {contact} ({title}). They currently run {competitor} and are frustrated with "
        "query latency on month-end reporting. Main goal: consolidate {n} data sources into one platform. "
        "Budget is approved for this fiscal year. Next step: technical deep-dive with their data team.",
        "Check-in call with {contact}. They confirmed the {product} pilot is going well; dashboards load in "
        "under 2 seconds versus 20+ before. Concern raised about renewal pricing - asked whether multi-year "
        "commitment unlocks a discount.",
        "Call with {contact} about procurement timeline. Legal review of the MSA is underway; redlines expected "
        "in two weeks. {contact} flagged that the CFO wants a clear ROI model before signing.",
        "Short call: {contact} said the project is on hold until the reorg finishes next quarter. Champion still "
        "supportive but has lost budget authority. Risk to the close date.",
    ],
    "Email": [
        "Sent {contact} the security questionnaire responses and SOC 2 Type II report. They asked about data "
        "residency for EU customers and whether we support customer-managed encryption keys.",
        "{contact} replied to the proposal: pricing is about 15% above their budget. They asked if Premium "
        "Support can be bundled at no extra cost for the first year.",
        "Follow-up email to {contact} recapping the demo, attaching the {product} datasheet and three customer "
        "case studies in {industry}.",
        "{contact} emailed asking for references from another {industry} customer of similar size before the "
        "steering committee meeting.",
    ],
    "Meeting": [
        "On-site meeting with {contact} and the data team. Whiteboarded the target architecture: streaming "
        "ingestion via Data Connectors Pack into Core Platform, with Analytics Add-on for exec dashboards. "
        "They want SSO via Okta and row-level security.",
        "Quarterly business review with {contact}. Adoption is up 40% quarter over quarter, 180 weekly active "
        "users. They are interested in expanding to the finance department and evaluating AI Assist.",
        "Executive alignment meeting. {contact} shared that {competitor} offered a steep discount. We emphasized "
        "lower total cost of ownership and faster time to value. Decision expected by end of month.",
    ],
    "Demo": [
        "Product demo of {product} for {contact} and 6 attendees. Strong reaction to natural-language querying in "
        "AI Assist. Questions about API rate limits and how lineage is tracked.",
        "Technical demo focused on Data Connectors Pack: showed SAP and Salesforce connectors. {contact} asked "
        "whether a custom connector for their on-prem Oracle database is possible.",
    ],
    "Support Ticket": [
        "Ticket opened by {contact}: scheduled reports failing intermittently since the last upgrade. Severity 2. "
        "Engineering identified a timezone bug; hotfix scheduled. Customer frustrated with response time.",
        "Ticket: {contact} requested help configuring SAML SSO. Resolved within 4 hours, customer satisfied.",
        "Ticket: dashboard performance degradation for large tables (over 500M rows). Recommended enabling "
        "aggregation caching. Customer asked whether Premium Support would give faster escalation.",
    ],
    "Note": [
        "Internal note: champion {contact} is leaving the company next month. Need to build a relationship with "
        "the new VP before renewal.",
        "Internal note: account is expanding headcount in data engineering; strong upsell signal for AI Assist "
        "and additional Core Platform seats.",
    ],
}

SENTIMENT_HINTS = {
    "frustrated": "negative", "on hold": "negative", "above their budget": "negative",
    "steep discount": "negative", "leaving the company": "negative", "Risk": "negative",
    "going well": "positive", "Strong reaction": "positive", "Adoption is up": "positive",
    "satisfied": "positive", "upsell": "positive", "approved": "positive",
}

LOSS_REASONS = ["Lost to competitor on price", "No decision / project cancelled",
                "Chose in-house build", "Budget cut"]


def _sentiment(text: str) -> str:
    for hint, sentiment in SENTIMENT_HINTS.items():
        if hint in text:
            return sentiment
    return "neutral"


def generate(now: datetime | None = None, seed: int = SEED) -> dict[str, list[dict]]:
    """Return {collection: [documents]} - pure function, no database access."""
    rng = random.Random(seed)
    now = (now or datetime.now()).replace(microsecond=0)
    today = now.replace(hour=0, minute=0, second=0)

    def past(min_days: int, max_days: int) -> datetime:
        return now - timedelta(days=rng.randint(min_days, max_days), hours=rng.randint(0, 9))

    data: dict[str, list[dict]] = {k: [] for k in
                                   ("accounts", "contacts", "opportunities", "leads", "interactions", "tasks")}

    # ---- accounts -----------------------------------------------------------------------
    for i, (name, industry, region, country, city, employees) in enumerate(ACCOUNTS, 1):
        if employees >= 15000:
            tier = "Strategic"
        elif employees >= 5000:
            tier = "Enterprise"
        elif employees >= 1000:
            tier = "Mid-Market"
        else:
            tier = "SMB"
        status = rng.choices(["Customer", "Prospect", "Churned"], weights=[55, 38, 7])[0]
        if i in (9, 21):  # guarantee a couple of churned accounts for win-back scenarios
            status = "Churned"
        data["accounts"].append({
            "_id": f"ACC-{i:03d}",
            "name": name,
            "industry": industry,
            "website": f"https://www.{name.lower().replace(' ', '').replace('&', '')}.example.com",
            "employees": employees,
            "annual_revenue": employees * rng.randint(180_000, 420_000),
            "region": region,
            "country": country,
            "city": city,
            "tier": tier,
            "status": status,
            "owner": REPS[(i - 1) % len(REPS)],
            "health_score": rng.randint(35, 98) if status == "Customer" else None,
            "arr": rng.choice([60000, 84000, 120000, 156000, 240000, 310000]) if status == "Customer" else 0,
            "renewal_date": (today + timedelta(days=rng.randint(20, 330))) if status == "Customer" else None,
            "tags": rng.sample(["data-warehouse", "bi-replacement", "ai-curious", "security-sensitive",
                                "multi-region", "price-sensitive", "fast-growing"], k=2),
            "created_at": past(200, 900),
        })

    # ---- contacts -----------------------------------------------------------------------
    cid = 0
    contacts_by_account: dict[str, list[dict]] = {}
    for acc in data["accounts"]:
        n = rng.randint(2, 5)
        roles = rng.sample(ROLES, k=n)
        for j, (title, dept, seniority) in enumerate(roles):
            cid += 1
            first, last = rng.choice(FIRST), rng.choice(LAST)
            domain = acc["website"].split("www.")[1]
            doc = {
                "_id": f"CON-{cid:03d}",
                "account_id": acc["_id"],
                "first_name": first,
                "last_name": last,
                "full_name": f"{first} {last}",
                "email": f"{first.lower()}.{last.lower()}@{domain}".replace("ü", "u"),
                "phone": f"+1-555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}",
                "title": title,
                "department": dept,
                "seniority": seniority,
                "is_primary": j == 0,
                "created_at": acc["created_at"] + timedelta(days=rng.randint(0, 60)),
            }
            data["contacts"].append(doc)
            contacts_by_account.setdefault(acc["_id"], []).append(doc)

    # ---- opportunities ------------------------------------------------------------------
    oid = 0
    for acc in data["accounts"]:
        count = 0 if acc["status"] == "Churned" else rng.choice([1, 1, 2, 2, 3])
        for _ in range(count):
            oid += 1
            products = rng.sample(list(PRODUCTS), k=rng.randint(1, 3))
            if acc["status"] == "Customer" and "Core Platform" in products and rng.random() < 0.5:
                products.remove("Core Platform")  # existing customers mostly buy add-ons
                products = products or ["AI Assist"]
            seats = rng.choice([1, 1, 1.5, 2, 3])
            amount = int(sum(PRODUCTS[p] for p in products) * seats)
            stage, prob = rng.choices(STAGES, weights=[14, 18, 20, 16, 20, 12])[0]
            closed = stage.startswith("Closed")
            lo, hi = CLOSE_WINDOW[stage]  # later stages close sooner; a few open deals are past due
            close_date = today + timedelta(days=rng.randint(lo, hi))
            kind = "Expansion" if acc["status"] == "Customer" else "New Business"
            primary = contacts_by_account[acc["_id"]][0]
            created = close_date - timedelta(days=rng.randint(45, 160))
            data["opportunities"].append({
                "_id": f"OPP-{oid:03d}",
                "account_id": acc["_id"],
                "name": f"{acc['name']} - {kind} - {' + '.join(products)}",
                "type": kind,
                "stage": stage,
                "amount": amount,
                "probability": prob,
                "close_date": close_date,
                "owner": acc["owner"],
                "products": products,
                "primary_contact_id": primary["_id"],
                "competitor": rng.choice(COMPETITORS + [None, None]),
                "next_step": None if closed else rng.choice(NEXT_STEPS[stage]),
                "loss_reason": rng.choice(LOSS_REASONS) if stage == "Closed Lost" else None,
                "created_at": min(created, now),
                "updated_at": past(0, 25) if not closed else close_date,
            })

    # ---- leads --------------------------------------------------------------------------
    for i, (company, industry) in enumerate(LEAD_COMPANIES, 1):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        status = rng.choices(["New", "Working", "Qualified", "Unqualified"], weights=[30, 30, 25, 15])[0]
        title, _, _ = rng.choice(ROLES)
        data["leads"].append({
            "_id": f"LEAD-{i:03d}",
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}",
            "company": company,
            "title": title,
            "email": f"{first.lower()}.{last.lower()}@{company.lower().replace(' ', '').replace('&', '')}.example.com"
                     .replace("ü", "u").replace("'", ""),
            "industry": industry,
            "source": rng.choice(LEAD_SOURCES),
            "status": status,
            "score": rng.randint(55, 98) if status == "Qualified" else
                     rng.randint(5, 40) if status == "Unqualified" else rng.randint(20, 85),
            "interest": rng.choice(LEAD_INTERESTS),
            "estimated_employees": rng.choice([120, 400, 900, 2500, 6000, 15000]),
            "owner": rng.choice(REPS),
            "converted_account_id": None,
            "created_at": past(1, 90),
        })

    # ---- interactions -------------------------------------------------------------------
    iid = 0

    def add_interaction(itype: str, ts: datetime, owner: str, text: str, **links) -> None:
        nonlocal iid
        iid += 1
        data["interactions"].append({
            "_id": f"INT-{iid:04d}",
            "type": itype,
            "subject": text.split(".")[0][:90],
            "notes": text,
            "sentiment": _sentiment(text),
            "timestamp": ts,
            "owner": owner,
            "account_id": links.get("account_id"),
            "contact_id": links.get("contact_id"),
            "opportunity_id": links.get("opportunity_id"),
            "lead_id": links.get("lead_id"),
        })

    opps_by_account: dict[str, list[dict]] = {}
    for opp in data["opportunities"]:
        opps_by_account.setdefault(opp["account_id"], []).append(opp)

    for acc in data["accounts"]:
        n = rng.randint(3, 9) if acc["status"] != "Churned" else 2
        for _ in range(n):
            itype = rng.choices(list(NOTE_TEMPLATES), weights=[25, 25, 15, 10, 15, 10])[0]
            if itype == "Support Ticket" and acc["status"] != "Customer":
                itype = "Email"
            contact = rng.choice(contacts_by_account[acc["_id"]])
            opp = rng.choice(opps_by_account.get(acc["_id"], [None]))
            text = rng.choice(NOTE_TEMPLATES[itype]).format(
                contact=contact["full_name"], title=contact["title"], competitor=rng.choice(COMPETITORS),
                n=rng.randint(4, 15), industry=acc["industry"].lower(),
                product=rng.choice(opp["products"]) if opp else rng.choice(list(PRODUCTS)))
            add_interaction(itype, past(0, 120), acc["owner"], text, account_id=acc["_id"],
                            contact_id=contact["_id"], opportunity_id=opp["_id"] if opp else None)

    for lead in data["leads"]:
        if lead["status"] == "New":
            continue
        text = rng.choice([
            f"Intro call with {lead['full_name']} from {lead['company']}. Interested in {lead['interest'].lower()}. "
            f"Team of roughly {lead['estimated_employees'] // 50} analysts. Asked for pricing overview.",
            f"Emailed {lead['full_name']} a follow-up after the {lead['source'].lower()}. They want a demo next "
            "month and mentioned evaluating two other vendors.",
            f"{lead['full_name']} replied that timing is not right; revisit next quarter.",
        ])
        add_interaction(rng.choice(["Call", "Email"]), past(0, 60), lead["owner"], text, lead_id=lead["_id"])

    data["interactions"].sort(key=lambda d: d["timestamp"])

    # ---- tasks --------------------------------------------------------------------------
    tid = 0
    for opp in data["opportunities"]:
        if opp["next_step"] and rng.random() < 0.7:
            tid += 1
            due = today + timedelta(days=rng.randint(-7, 21))
            data["tasks"].append({
                "_id": f"TASK-{tid:03d}",
                "subject": f"{opp['next_step']} ({opp['name'].split(' - ')[0]})",
                "due_date": due,
                "status": "Open",
                "priority": rng.choice(["High", "Normal", "Normal", "Low"]),
                "owner": opp["owner"],
                "account_id": opp["account_id"],
                "opportunity_id": opp["_id"],
                "lead_id": None,
                "created_at": past(1, 20),
            })

    return data


def seed_database(db, *, reset: bool = False, now: datetime | None = None) -> dict[str, int]:
    from .db import COLLECTIONS

    if reset:
        for coll in COLLECTIONS:
            db[coll].delete_many({})
    data = generate(now=now)
    for coll, docs in data.items():
        if docs:
            db[coll].insert_many(docs)
    return {coll: len(docs) for coll, docs in data.items()}


def main() -> None:
    from . import db as dbmod

    parser = argparse.ArgumentParser(description="Seed the CRM database with dummy data")
    parser.add_argument("--reset", action="store_true", help="wipe existing data first")
    args = parser.parse_args()

    if not dbmod.settings.mongo_uri and args.reset and dbmod.settings.snapshot_path.exists():
        dbmod.settings.snapshot_path.unlink()
    db = dbmod.connect(auto_seed=False)
    if db.accounts.count_documents({}) and not args.reset:
        print(f"Database already seeded ({dbmod.backend_name(db)}). Use --reset to re-seed.")
        return
    counts = seed_database(db, reset=args.reset)
    dbmod.ensure_indexes(db)
    dbmod.save_snapshot(db)
    print(f"Seeded {dbmod.backend_name(db)}:")
    for coll, n in counts.items():
        print(f"  {coll:<14}{n:>5}")


if __name__ == "__main__":
    main()
