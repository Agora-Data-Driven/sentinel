"""Service templates — the recipe book that auto-fills a task's work breakdown per department.

Picking a **Service type** on the New Task form (filtered by the assigned department) pre-builds the
whole two-level breakdown — **main tasks, each with its sub-tasks** — so the team starts from a
filled-in plan instead of retyping the same phases for every job.

Departments are matched by **team name** (Sentinel seeds Acquisition / Lifecycle / Data Analyst /
Development — the same taxonomy Atrium uses), so the service-type picker is really a department
filter. A template is a seed, not a lock: once created, the breakdown is ordinary data the detail
drawer edits freely (rename, add, assign, delete).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ServiceTemplate
from . import maintasks as MT

# key -> {dept (team name), label, content_type, groups:[(main-task title, [sub-task text, ...]), ...]}
# NOTE: this dict is now only the ONE-TIME SEED for the DB-backed `service_templates` table
# (written by main._seed_config on first boot). After that, the catalog is edited in the Manage page
# and read from the DB — editing this dict no longer changes a running instance.
SEED_TEMPLATES: dict[str, dict] = {
    # --- Acquisition ---------------------------------------------------------
    "google_meta_campaign": {
        "dept": "Acquisition", "label": "Google / Meta Campaign", "content_type": "Campaign",
        "groups": [
            ("Campaign build", [
                "Audience, interest & budget research",
                "Campaign structure plan (objective + conversion event) approved",
                "Audience build (custom / lookalike / interest) saved in Ads Manager",
                "Ad set configuration — placements, schedule, budget",
                "Load creatives + copy (headlines, primary text, CTAs)",
                "Compliance check against client rules",
            ]),
            ("Launch & verify", [
                "Tracking confirmation (pixel / CAPI events firing)",
                "Launch — campaign published, ID logged on the card",
                "Post-launch QA (24h): delivery, spend pacing, attribution",
            ]),
        ],
    },

    # --- Lifecycle -----------------------------------------------------------
    "email_automation": {
        "dept": "Lifecycle", "label": "Email Automation / Sequence Build", "content_type": "Email Automation",
        "groups": [
            ("Plan", ["Automation map (trigger, waits, if/else, exit) documented"]),
            ("Email production", ["Email copy drafted to the approved angle", "Email HTML build — responsive, merge fields correct"]),
            ("Build & activate", [
                "Automation built in platform (steps, conditions, tags)",
                "Entry points connected (forms / links / imports)",
                "End-to-end test with a test contact",
                "Activate — sequence live, logged on the card",
            ]),
        ],
    },
    "content_cycle": {
        "dept": "Lifecycle", "label": "Content Cycle (theme)", "content_type": "Content",
        "groups": [
            ("Plan", ["Topic ideation approved", "Angle brief written"]),
            ("Write", ["Anchor blog drafted and reviewed", "Supporting blogs drafted against the angle brief", "Newsletter drafted from the theme"]),
            ("Produce & publish", ["Blog graphics produced", "Publish — all pieces live, URLs logged"]),
        ],
    },
    "organic_social": {
        "dept": "Lifecycle", "label": "Organic Social Post Production", "content_type": "Social",
        "groups": [
            ("Post batch", ["Concept + caption approved", "Design to brand spec", "Approver sign-off on the batch", "Scheduled per cadence, logged"]),
        ],
    },

    # --- Data Analyst --------------------------------------------------------
    "market_research": {
        "dept": "Data Analyst", "label": "Market Research Package", "content_type": "Research",
        "groups": [
            ("Research package", [
                "Company profile — what they do, offer, positioning",
                "Brand / business identity — voice, values, differentiators",
                "PESTEL analysis (all six factors)",
                "Industry overview — market size, dynamics, key players",
                "Competitor research (3+ competitors profiled)",
                "Trend research — current demand + content trends",
                "Link the research doc in the central sheet",
            ]),
        ],
    },
    "dashboard_build": {
        "dept": "Data Analyst", "label": "Dashboard Build", "content_type": "Dashboard",
        "groups": [
            ("Define & connect", ["Define metrics + source per metric with the requester", "Connect all data sources"]),
            ("Build & hand over", ["Build the agreed views", "Validate numbers against source-of-truth spot checks", "Share access + walkthrough"]),
        ],
    },

    # --- Development ---------------------------------------------------------
    "tracking_setup": {
        "dept": "Development", "label": "Tracking Infrastructure Setup", "content_type": "Tracking",
        "groups": [
            ("Install", ["GTM container installed, publish access confirmed", "GA4 connected and receiving data", "Meta Pixel installed and firing", "Meta CAPI configured and deduplicating"]),
            ("Configure & verify", ["Conversion events / triggers built and named per convention", "UTM scheme documented", "QA / verify events in GTM Preview + GA4 Realtime"]),
        ],
    },
    "website_fix": {
        "dept": "Development", "label": "Website Edit / Fix / Integration", "content_type": "Website",
        "groups": [
            ("Fix", ["Change implemented on staging or live", "Integration connected (payment / form / pixel)", "Verified working in production"]),
        ],
    },
}


def seed_rows() -> list[dict]:
    """The rows main._seed_config writes into `service_templates` on first boot (recipe = raw groups,
    no ids — MT.normalize assigns fresh ids each time a task is seeded from it)."""
    import json
    rows = []
    for i, (key, t) in enumerate(SEED_TEMPLATES.items()):
        groups = [{"title": title, "subs": [{"text": s} for s in subs]} for title, subs in t["groups"]]
        rows.append({"key": key, "label": t["label"], "dept": t["dept"],
                     "content_type": t["content_type"], "maintasks_json": json.dumps(groups),
                     "sort_order": i})
    return rows


def get(db: Session, key: str | None):
    """The ServiceTemplate row for a key (active only), or None."""
    key = (key or "").strip()
    if not key:
        return None
    return db.execute(
        select(ServiceTemplate).where(ServiceTemplate.key == key, ServiceTemplate.is_active.is_(True))
    ).scalar_one_or_none()


def maintasks_for(db: Session, key: str | None) -> list[dict]:
    """Fresh two-level breakdown seeded from a template: [{id,title,assignee_id,subs:[...]}]."""
    row = get(db, key)
    return MT.normalize(row.maintasks_json) if row else []


def catalog(db: Session) -> list[dict]:
    """Render-ready list for the New Task picker, from the DB. `steps` = flat count for the preview;
    `groups` = the main-task structure the task is seeded with."""
    rows = db.execute(
        select(ServiceTemplate).where(ServiceTemplate.is_active.is_(True))
        .order_by(ServiceTemplate.sort_order, ServiceTemplate.id)
    ).scalars().all()
    out = []
    for r in rows:
        groups = MT.normalize(r.maintasks_json)  # gives {title, subs:[{text,...}]}
        out.append({
            "key": r.key, "dept": r.dept, "label": r.label, "content_type": r.content_type,
            "steps": [s["text"] for g in groups for s in g["subs"]],
            "groups": [{"title": g["title"], "subs": [{"text": s["text"]} for s in g["subs"]]} for g in groups],
        })
    return out
