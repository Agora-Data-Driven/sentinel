"""Service templates — the recipe book that auto-fills a task's checklist per department.

Picking a **Service type** on the New Task form (filtered by the assigned department) pre-fills the
whole checklist from a filled-in starting point, so the team stops retyping the same steps for every
recurring job. This is Sentinel's flattened take on Atrium's `service_templates.py`: Atrium builds a
two-level `maintasks[]/subs[]` tree, but Sentinel tasks store a **flat** `checklist[]`, so each recipe
here is just an ordered list of checklist item texts.

Departments are matched by **team name** (Sentinel seeds Acquisition / Lifecycle / Data Analyst /
Development — the same taxonomy Atrium uses), so the service-type picker is really a department
filter. A template is a seed, not a lock: once a task is created the checklist is ordinary data the
detail drawer edits freely.
"""
from __future__ import annotations

# key -> {dept (team name), label, content_type, checklist:[step text, ...]}
TEMPLATES: dict[str, dict] = {
    # --- Acquisition ---------------------------------------------------------
    "google_meta_campaign": {
        "dept": "Acquisition", "label": "Google / Meta Campaign", "content_type": "Campaign",
        "checklist": [
            "Audience, interest & budget research",
            "Campaign structure plan (objective + conversion event) approved",
            "Audience build (custom / lookalike / interest) saved in Ads Manager",
            "Ad set configuration — placements, schedule, budget",
            "Load creatives + copy (headlines, primary text, CTAs)",
            "Compliance check against client rules",
            "Tracking confirmation (pixel / CAPI events firing)",
            "Launch — campaign published, ID logged on the card",
            "Post-launch QA (24h): delivery, spend pacing, attribution",
        ],
    },

    # --- Lifecycle -----------------------------------------------------------
    "email_automation": {
        "dept": "Lifecycle", "label": "Email Automation / Sequence Build", "content_type": "Email Automation",
        "checklist": [
            "Automation map (trigger, waits, if/else, exit) documented",
            "Email copy drafted to the approved angle",
            "Email HTML build — responsive, merge fields correct",
            "Automation built in platform (steps, conditions, tags)",
            "Entry points connected (forms / links / imports)",
            "End-to-end test with a test contact",
            "Activate — sequence live, logged on the card",
        ],
    },
    "content_cycle": {
        "dept": "Lifecycle", "label": "Content Cycle (theme)", "content_type": "Content",
        "checklist": [
            "Topic ideation approved",
            "Angle brief written",
            "Anchor blog drafted and reviewed",
            "Supporting blogs drafted against the angle brief",
            "Newsletter drafted from the theme",
            "Blog graphics produced",
            "Publish — all pieces live, URLs logged",
        ],
    },
    "organic_social": {
        "dept": "Lifecycle", "label": "Organic Social Post Production", "content_type": "Social",
        "checklist": [
            "Concept + caption approved",
            "Design to brand spec",
            "Approver sign-off on the batch",
            "Scheduled per cadence, logged",
        ],
    },

    # --- Data Analyst --------------------------------------------------------
    "market_research": {
        "dept": "Data Analyst", "label": "Market Research Package", "content_type": "Research",
        "checklist": [
            "Company profile — what they do, offer, positioning",
            "Brand / business identity — voice, values, differentiators",
            "PESTEL analysis (all six factors)",
            "Industry overview — market size, dynamics, key players",
            "Competitor research (3+ competitors profiled)",
            "Trend research — current demand + content trends",
            "Link the research doc in the central sheet",
        ],
    },
    "dashboard_build": {
        "dept": "Data Analyst", "label": "Dashboard Build", "content_type": "Dashboard",
        "checklist": [
            "Define metrics + source per metric with the requester",
            "Connect all data sources",
            "Build the agreed views",
            "Validate numbers against source-of-truth spot checks",
            "Share access + walkthrough",
        ],
    },

    # --- Development ---------------------------------------------------------
    "tracking_setup": {
        "dept": "Development", "label": "Tracking Infrastructure Setup", "content_type": "Tracking",
        "checklist": [
            "GTM container installed, publish access confirmed",
            "GA4 connected and receiving data",
            "Meta Pixel installed and firing",
            "Meta CAPI configured and deduplicating",
            "Conversion events / triggers built and named per convention",
            "UTM scheme documented",
            "QA / verify events in GTM Preview + GA4 Realtime",
        ],
    },
    "website_fix": {
        "dept": "Development", "label": "Website Edit / Fix / Integration", "content_type": "Website",
        "checklist": [
            "Change implemented on staging or live",
            "Integration connected (payment / form / pixel)",
            "Verified working in production",
        ],
    },
}


def get(key: str | None) -> dict | None:
    """The template dict for a service key, or None."""
    return TEMPLATES.get((key or "").strip())


def checklist_for(key: str | None) -> list[dict]:
    """The seeded checklist for a service key: [{text, done:False}, ...] (empty on unknown key)."""
    tpl = get(key)
    if not tpl:
        return []
    return [{"text": step, "done": False} for step in tpl["checklist"]]


def catalog() -> list[dict]:
    """Render-ready list for the New Task picker: [{key, dept, label, content_type, steps:[...]}]."""
    return [
        {"key": k, "dept": t["dept"], "label": t["label"],
         "content_type": t["content_type"], "steps": list(t["checklist"])}
        for k, t in TEMPLATES.items()
    ]
