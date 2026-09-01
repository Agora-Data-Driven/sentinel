"""AI TASK DRAFTING — plain words in, PROPOSED tasks out, a human creates them (2026-09-02).

The account manager types what was agreed with a client ("we promised TCS the September Meta
analysis before Thursday's meeting; Earl does the review first, then Leo adds it to the report") and
this module answers with structured proposals: title, department, suggested assignee, due date,
estimate, reviewer, dependency, and WHY. The UI shows them; the person edits and presses Create; the
creation then goes through `POST /api/tasks` with every permission, label and origin rule intact.

Three rules:

* **Propose, never write.** This module has no database write. It returns dicts.
* **Ground every suggestion in Sentinel's own facts** — the client's current cards, who holds them per
  department, who is on leave, who is heavy, who is a Shadow/Contributor (needs a reviewer), who holds
  the certification a template requires. The model picks from a roster it is given; it cannot invent a
  colleague. Warnings are computed HERE from those facts, not trusted from the model.
* **Fail soft, say so.** No Vertex, no credentials, a bad answer → `(None, reason)` and the button
  says "AI unavailable — file it by hand". The fallback is the New Task form, which always works.

Transport: Vertex AI `generateContent` with the Cloud Run runtime service account's token from the
metadata server — GCP-billed, no API key — the same pattern Atrium's `intel_ai.py` uses. The runtime
SA needs `roles/aiplatform.user`.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..constants import STAGE_LABELS, STAGES_NEED_REVIEWER
from ..models import Certification, Client, LeaveRequest, ServiceTemplate, Task, Team, User
from ..constants import LEAVE_APPROVED
from ..serializers import user_public
from ..utils.time import today_ph
from . import task_analytics, task_config, task_perms
from . import teams as teams_svc

log = logging.getLogger(__name__)

_METADATA_TOKEN_URL = ("http://metadata.google.internal/computeMetadata/v1/instance/"
                       "service-accounts/default/token")
_TIMEOUT = 45
_token_cache: dict = {"value": "", "expires": 0.0}

SYSTEM = """You turn an account manager's plain-language commitment into 1–5 tasks for a digital
marketing agency's task board. You are given the client, today's date, the departments, the people
(with department, stage, current load, leave) and which people already hold this client's work in
each department. Rules:
- Split by DELIVERABLE, one task per person-sized piece of work. Do not invent work not implied.
- department must be one of the given department names.
- assignee must be one of the given people ids, chosen in this order: the person already holding
  this client's work in that department; else someone in that department who is not on leave and
  not heavy. If nobody fits, use null.
- reviewer: a team lead or account manager id when the assignee's stage is shadow or contributor,
  else null.
- due_date ISO YYYY-MM-DD, never in the past; infer from words like "before Thursday's meeting".
- estimate_minutes: a realistic whole number (30–480).
- depends_on: the 1-based index of an earlier task this one waits for, else null.
- why: one sentence a manager can read explaining the assignee and date.
Answer ONLY with JSON: {"tasks":[{"title","description","department","assignee_id","reviewer_id",
"due_date","estimate_minutes","depends_on","why"}]}"""


def enabled() -> bool:
    return bool(settings.vertex_gemini_enabled and (settings.vertex_project or "").strip())


def _gcp_token() -> str:
    now = time.time()
    if _token_cache["value"] and _token_cache["expires"] > now + 60:
        return _token_cache["value"]
    req = urllib.request.Request(_METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=5) as resp:          # noqa: S310 — fixed metadata URL
        data = json.loads(resp.read().decode("utf-8"))
    _token_cache["value"] = data.get("access_token", "")
    _token_cache["expires"] = now + int(data.get("expires_in") or 3000)
    return _token_cache["value"]


def _generate_text(system: str, user: str) -> tuple[str, str]:
    """One Vertex call. Returns (text, error). Module-level so tests can monkeypatch it."""
    try:
        token = _gcp_token()
    except Exception as exc:                                       # noqa: BLE001
        return "", f"could not get GCP credentials for Vertex ({type(exc).__name__})"
    loc = settings.vertex_location or "global"
    host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
    url = (f"https://{host}/v1/projects/{settings.vertex_project}/locations/{loc}"
           f"/publishers/google/models/{settings.vertex_model}:generateContent")
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"response_mime_type": "application/json", "maxOutputTokens": 4096,
                             "thinkingConfig": {"thinkingBudget": 0 if "flash" in settings.vertex_model else 128}},
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:   # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        return "", f"Vertex answered {exc.code}: {body}"
    except Exception as exc:                                       # noqa: BLE001
        return "", f"could not reach Vertex AI ({type(exc).__name__})"
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip(), ""
    except Exception:                                              # noqa: BLE001
        return "", "Vertex returned an unexpected response"


# --- context ---------------------------------------------------------------------------------------

def context(db: Session, client: Client | None, today: date | None = None) -> dict:
    today = today or today_ph()
    teams = db.execute(select(Team).order_by(Team.name)).scalars().all()
    users = db.execute(select(User).where(User.is_active.is_(True), User.role != "viewer")
                       .order_by(User.name)).scalars().all()
    team_name = {t.id: t.name for t in teams}
    open_tasks = db.execute(select(Task).where(Task.archived.is_(False))).scalars().all()
    stage_of = {s: task_config.stage_for(db, s) for s in {t.status for t in open_tasks}}
    open_tasks = [t for t in open_tasks if stage_of.get(t.status) != "completed"]
    leave = task_analytics.leave_context(db, [u.id for u in users], today, ahead_days=7)
    rows = [{"user": user_public(u), "open_total": len([t for t in open_tasks if u.id in task_perms.assigned_user_ids(t)])}
            for u in users]
    task_analytics.apply_load_bands(rows)
    band = {r["user"]["id"]: r.get("load_band") for r in rows}
    certs: dict[int, list[str]] = {}
    for c in db.execute(select(Certification)).scalars():
        if c.is_valid(today):
            certs.setdefault(c.user_id, []).append(c.key)
    people = []
    for u in users:
        depts = [team_name[t] for t in teams_svc.team_ids(u) if t in team_name]
        people.append({
            "id": u.id, "name": u.name, "role": u.role,
            "stage": getattr(u, "stage", None),
            "departments": depts,
            "load": band.get(u.id) or "light",
            "open_cards": next((r["open_total"] for r in rows if r["user"]["id"] == u.id), 0),
            "on_leave_today": bool((leave.get(u.id) or {}).get("on_leave_today")),
            "leave_days_next_week": (leave.get(u.id) or {}).get("leave_days_ahead", 0),
            "certifications": certs.get(u.id, []),
        })
    holders: dict[str, list[int]] = {}
    client_cards = []
    if client is not None:
        for t in open_tasks:
            if t.client_id == client.id:
                client_cards.append({"title": t.title, "department": team_name.get(t.assigned_team_id),
                                     "assignee_id": t.assigned_to_id, "status": t.status,
                                     "due_date": t.due_date.isoformat() if t.due_date else None})
                if t.assigned_team_id and t.assigned_to_id:
                    holders.setdefault(team_name[t.assigned_team_id], [])
                    if t.assigned_to_id not in holders[team_name[t.assigned_team_id]]:
                        holders[team_name[t.assigned_team_id]].append(t.assigned_to_id)
    templates = [{"key": s.key, "label": s.label, "department": s.dept,
                  "estimate_minutes": getattr(s, "estimate_minutes", None),
                  "required_certification": getattr(s, "required_certification", None)}
                 for s in db.execute(select(ServiceTemplate).where(ServiceTemplate.is_active.is_(True))).scalars()]
    return {
        "today": today.isoformat(),
        "weekday": today.strftime("%A"),
        "client": {"id": client.id, "name": client.name,
                   "account_manager_id": client.account_manager_id} if client else None,
        "departments": [t.name for t in teams],
        "people": people,
        "holders_by_department": holders,
        "client_open_cards": client_cards,
        "templates": templates,
        "_team_ids": {t.name: t.id for t in teams},
        "_people": {p["id"]: p for p in people},
    }


# --- parsing + validation --------------------------------------------------------------------------

def _parse_json(text: str) -> dict | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        val = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            return None
        try:
            val = json.loads(m.group(0))
        except ValueError:
            return None
    return val if isinstance(val, dict) else None


def _iso(v) -> str | None:
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def validate(raw: dict, ctx: dict, today: date | None = None) -> list[dict]:
    """Coerce the model's answer into proposals the New Task form can take, and compute WARNINGS
    from Sentinel's facts (never trusted from the model)."""
    today = today or today_ph()
    team_ids: dict[str, int] = ctx["_team_ids"]
    people: dict[int, dict] = ctx["_people"]
    lower_teams = {k.lower(): v for k, v in team_ids.items()}
    tmpl_by_dept: dict[str, list[dict]] = {}
    for t in ctx["templates"]:
        if t["department"]:
            tmpl_by_dept.setdefault(t["department"].lower(), []).append(t)
    out: list[dict] = []
    for i, item in enumerate((raw or {}).get("tasks") or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:200]
        if not title:
            continue
        dept_name = str(item.get("department") or "").strip()
        team_id = lower_teams.get(dept_name.lower())
        assignee = item.get("assignee_id")
        assignee = int(assignee) if isinstance(assignee, (int, float)) or (isinstance(assignee, str) and assignee.isdigit()) else None
        if assignee not in people:
            assignee = None
        reviewer = item.get("reviewer_id")
        reviewer = int(reviewer) if isinstance(reviewer, (int, float)) or (isinstance(reviewer, str) and reviewer.isdigit()) else None
        if reviewer not in people:
            reviewer = None
        due = _iso(item.get("due_date"))
        if due and due < today.isoformat():
            due = today.isoformat()
        est = item.get("estimate_minutes")
        est = int(est) if isinstance(est, (int, float)) and 5 <= est <= 24 * 60 else None
        dep = item.get("depends_on")
        dep = int(dep) if isinstance(dep, (int, float)) and 1 <= int(dep) <= i else None
        warnings: list[str] = []
        p = people.get(assignee) if assignee else None
        if p:
            if p["on_leave_today"] or p["leave_days_next_week"]:
                warnings.append(f"{p['name']} has leave booked in the next week.")
            if p["load"] == "heavy":
                warnings.append(f"{p['name']} is carrying more than the team already.")
            if p.get("stage") in STAGES_NEED_REVIEWER and not reviewer:
                warnings.append(f"{p['name']} is a {STAGE_LABELS.get(p['stage'], p['stage'])} — a reviewer is required on live client work.")
            if team_id and dept_name and dept_name not in p["departments"]:
                warnings.append(f"{p['name']} is not in {dept_name}.")
            needed = {t["required_certification"] for t in tmpl_by_dept.get(dept_name.lower(), [])
                      if t.get("required_certification")}
            missing = [c for c in needed if c not in p["certifications"]]
            if missing and len(needed) == 1:
                warnings.append(f"{p['name']} does not hold the {missing[0].replace('_', ' ')} certification this kind of work usually needs.")
        elif not assignee:
            warnings.append("No assignee suggested — it will land in the department's queue.")
        out.append({
            "index": i + 1,
            "title": title,
            "description": str(item.get("description") or "").strip()[:2000] or None,
            "department": dept_name or None,
            "assigned_team_id": team_id,
            "assigned_to_id": assignee,
            "assignee": {"id": p["id"], "name": p["name"], "stage": p.get("stage")} if p else None,
            "reviewer_id": reviewer,
            "reviewer": {"id": people[reviewer]["id"], "name": people[reviewer]["name"]} if reviewer else None,
            "due_date": due,
            "estimate_minutes": est,
            "depends_on": dep,
            "why": str(item.get("why") or "").strip()[:400],
            "warnings": warnings,
        })
    return out[:5]


def draft(db: Session, viewer: User, text: str, client: Client | None) -> tuple[list[dict] | None, str]:
    """(proposals, error). `proposals` is None when the model could not be asked or answered badly."""
    if not enabled():
        return None, "AI drafting is not switched on for this deployment."
    ctx = context(db, client)
    user_msg = json.dumps({
        "request": text.strip()[:4000],
        "today": ctx["today"], "weekday": ctx["weekday"],
        "client": ctx["client"], "departments": ctx["departments"],
        "people": ctx["people"], "holders_by_department": ctx["holders_by_department"],
        "client_open_cards": ctx["client_open_cards"][:40],
        "templates": ctx["templates"],
    }, ensure_ascii=False)
    answer, err = _generate_text(SYSTEM, user_msg)
    if err:
        log.warning("ai_draft: %s", err)
        return None, err
    raw = _parse_json(answer)
    if raw is None:
        return None, "The model did not answer with tasks."
    proposals = validate(raw, ctx)
    if not proposals:
        return None, "The model proposed nothing usable — file the task by hand."
    return proposals, ""
