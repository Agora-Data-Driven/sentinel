"""Mirror ATRIUM's client registry into Sentinel's `clients` table.

**The division of ownership, decided 2026-08-05:** Sentinel owns EMPLOYEES (its `users` table is the
source of truth for who the staff are, and every login authorizes against it); **Atrium owns
CLIENTS** (each one is a workspace in its registry, created and renamed there). Sentinel's `clients`
table used to be maintained BY HAND in Manage → Clients, which made it a second source of truth for
something Atrium already knew — and the two drifted, silently, in the one field that matters:

    🔴 `Client.atrium_client_id` is the BRIDGE KEY. `atrium_tasks.resolve_client` matches a client
    card to a Sentinel client with it, `task_bridge` needs it to know which workspace to publish
    into, `board_mirror` puts it in the payload Atrium pulls, and `task_adoption` REFUSES TO RUN
    without it ("its adopted cards will appear twice on the board"). Every one of those failures
    began as somebody not typing a workspace key into a form.

So the table stays — it is the FK target for `Task.client_id` and the local cache the board filters
on — but it is now FILLED by this module instead of by people. What the sync does, in order:

1. **Upsert by `atrium_client_id`.** A linked client's name follows Atrium's (that is what the
   console's Rename button edits, and what the client themselves sees).
2. **Adopt an unlinked client whose NAME unambiguously matches** an Atrium workspace — the same
   fallback `atrium_tasks.resolve_client` already uses, so this only writes down a link the board was
   already inferring at read time. Ambiguous or unmatched names are left alone.
3. **Deactivate the rest.** Never delete: `Task.client_id` would be nulled and every past task would
   lose its client, blanking historical reports. An inactive client keeps its history and drops out
   of the pickers.
4. **Reactivate** anything that comes back.

🔴 **The sync REFUSES to run on an empty or failed answer.** Deactivation is driven by absence, so
"Atrium didn't answer" and "Atrium has no clients" must never be confused — that mistake would
deactivate the entire estate in one pass. `atrium_tasks.fetch_clients` returns an explicit error for
this reason (it is the one read in that module that is not fail-soft), and a zero-length list with no
error is *also* refused: a real estate is never empty, and a registry that reads empty is a storage
problem, not news.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Client
from . import atrium_tasks

log = logging.getLogger(__name__)


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _match_by_name(unlinked: list[Client], name: str) -> Client | None:
    """The one unlinked Sentinel client whose name matches, or None if 0 or 2+ do.

    Ambiguity resolves to nothing, like every other identity match in this codebase
    (`atrium_identity`, `atrium_tasks.resolve_client`): linking the wrong workspace would publish one
    client's work onto another client's board, which is the worst outcome available here.
    """
    hits = [c for c in unlinked if _norm(c.name) == _norm(name)]
    return hits[0] if len(hits) == 1 else None


def sync(db: Session) -> dict:
    """Run the mirror. Returns a report; raises nothing.

    `{"ok": bool, "error": str, "created": n, "updated": n, "linked": n,
      "deactivated": n, "reactivated": n, "skipped": [names]}`
    """
    report = {"ok": False, "error": "", "created": 0, "updated": 0, "linked": 0,
              "deactivated": 0, "reactivated": 0, "skipped": []}

    rows, err = atrium_tasks.fetch_clients()
    if err:
        report["error"] = err
        return report
    if not rows:
        # See the module docstring: absence drives deactivation, so an empty answer is refused.
        report["error"] = ("Atrium returned no clients at all — refusing to sync, because that "
                           "would deactivate every client here.")
        return report

    existing = db.execute(select(Client)).scalars().all()
    by_key = {_norm(c.atrium_client_id): c for c in existing if c.atrium_client_id}
    seen: set[int] = set()

    for row in rows:
        key = (row.get("key") or "").strip()
        if not key:
            continue
        name = (row.get("name") or key).strip()[:120]
        email = (row.get("contact_email") or "").strip() or None

        client = by_key.get(_norm(key))
        if client is None:
            # Step 2: adopt by name before creating a duplicate of a client that already exists here.
            unlinked = [c for c in existing if not c.atrium_client_id and c.id not in seen]
            client = _match_by_name(unlinked, name)
            if client is not None:
                client.atrium_client_id = key
                by_key[_norm(key)] = client
                report["linked"] += 1

        if client is None:
            client = Client(name=_free_name(existing, name, key), atrium_client_id=key,
                            contact_email=email, is_active=True)
            db.add(client)
            existing.append(client)
            report["created"] += 1
        else:
            changed = False
            # Follow Atrium's rename, but only where the new name is actually free — a collision
            # would raise on commit and lose the entire sync, and a stale name is a cosmetic problem.
            if client.name != name:
                free = _free_name(existing, name, key, ignore=client)
                if free != client.name:
                    client.name = free
                    changed = True
            if email and client.contact_email != email:
                client.contact_email = email
                changed = True
            if not getattr(client, "is_active", True):
                client.is_active = True
                report["reactivated"] += 1
                changed = True
            if changed:
                report["updated"] += 1

        db.flush()                      # so a freshly created row has an id for `seen`
        seen.add(client.id)

    # Step 3: everything Atrium no longer lists. Deactivated, never deleted.
    for client in existing:
        if client.id in seen:
            continue
        if getattr(client, "is_active", True):
            client.is_active = False
            report["deactivated"] += 1
            report["skipped"].append(client.name)

    db.commit()
    report["ok"] = True
    log.info("client mirror: %s", {k: v for k, v in report.items() if k != "skipped"})
    return report


def _free_name(existing: list[Client], name: str, key: str, ignore: Client | None = None) -> str:
    """`name`, disambiguated by its workspace key if another client already holds it.

    🔴 `Client.name` is UNIQUE. Two Atrium workspaces can legitimately display the same name (one
    client with two brands, or a workspace recreated under a new key), and an IntegrityError there
    would abort the WHOLE mirror — one duplicate name would stop every other client syncing. So the
    later one becomes "Acme (acme-2)" rather than taking the estate's sync down with it.
    """
    taken = {_norm(c.name) for c in existing if c is not ignore}
    if _norm(name) not in taken:
        return name[:120]
    candidate = f"{name} ({key})"
    if _norm(candidate) not in taken:
        return candidate[:120]
    i = 2
    while _norm(f"{name} ({key} {i})") in taken:
        i += 1
    return f"{name} ({key} {i})"[:120]


def pending_link_report(db: Session) -> list[dict]:
    """Clients with no `atrium_client_id` — the ones the bridge cannot address.

    Surfaced read-only because every one of them is a latent adoption/publish failure, and the old
    answer ("go type the workspace key into Manage") is the hand-maintenance this replaced.
    """
    rows = db.execute(select(Client).where(Client.atrium_client_id.is_(None))).scalars().all()
    return [{"id": c.id, "name": c.name, "is_active": bool(getattr(c, "is_active", True))}
            for c in rows]
