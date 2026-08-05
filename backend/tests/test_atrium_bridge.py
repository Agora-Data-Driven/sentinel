"""The Atrium task bridge: Atrium owns client-facing tasks, this board is the team's window.

These pin the contract that took a full day to get right (2026-07-27):
  * Atrium and Sentinel agree on the SAME status set, so a card can cross unambiguously.
  * An Atrium card is identifiable and routes its edits back to Atrium, never to Postgres.
  * The bridge is fail-SOFT -- unconfigured or unreachable Atrium must never blank the board or
    500 the endpoint, because the team's internal rows still have to render.
"""

from __future__ import annotations

from app.constants import TASK_STATUSES
from app.services import atrium_bridge, atrium_tasks


def test_status_map_covers_every_sentinel_status():
    """Every Sentinel status must map to an Atrium stage, or a drag would silently 400."""
    for status in TASK_STATUSES:
        assert status in atrium_tasks.STAGE_BY_STATUS, f"no Atrium stage for {status!r}"


def test_split_id_recognises_atrium_cards_only():
    assert atrium_tasks.split_id("atrium:riverdance-rv:tk_123") == ("riverdance-rv", "tk_123")
    # A plain Sentinel row id must NOT be mistaken for an Atrium card.
    assert atrium_tasks.split_id("42") == ("", "")
    assert atrium_tasks.split_id("") == ("", "")
    assert atrium_tasks.split_id(None) == ("", "")


def test_board_card_shape_and_client_resolution():
    payload = {
        "atrium_id": "riverdance-rv:tk_9", "task_id": "tk_9", "client_key": "riverdance-rv",
        "client_name": "Riverdance RV", "title": "audit ads", "status": "To Do",
        "priority": "Medium", "client_facing": True, "checklist_total": 3, "checklist_done": 1,
    }
    card = atrium_tasks.as_board_card(payload)
    assert card["id"] == "atrium:riverdance-rv:tk_9"
    assert card["source"] == "atrium"
    assert card["title"] == "audit ads"
    assert card["status"] == "To Do"
    assert card["checklist_total"] == 3 and card["checklist_done"] == 1
    # client_facing is what "visible in Atrium" means from this side.
    assert card["atrium_visible"] is True
    # With no matching Sentinel client row, the card still names the client from Atrium.
    assert card["client_id"] is None and card["client_name"] == "Riverdance RV"

    class _C:
        id, name = 7, "Riverdance RV Resort"

    linked = atrium_tasks.as_board_card(payload, _C())
    # Resolved through Client.atrium_client_id, so the board's client filter works on it.
    assert linked["client_id"] == 7 and linked["client_name"] == "Riverdance RV Resort"


def test_bridge_is_off_and_silent_without_config(monkeypatch):
    """No secret / no URL => disabled, and every call degrades instead of raising."""
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "portal_login_url", "", raising=False)
    assert atrium_tasks.enabled() is False
    assert atrium_tasks.fetch_tasks() == []
    ok, err = atrium_tasks.move_task("c", "tk_1", "todo")
    assert ok is False and err


class _Client:
    def __init__(self, cid, name, atrium_client_id=None):
        self.id, self.name, self.atrium_client_id = cid, name, atrium_client_id


def test_resolve_client_prefers_the_explicit_link():
    """atrium_client_id always wins, even when another client's NAME looks like a better match."""
    rows = [_Client(1, "Riverdance RV"), _Client(2, "Something Else", "riverdance-rv")]
    assert atrium_tasks.resolve_client(rows, "riverdance-rv", "Riverdance RV").id == 2


def test_resolve_client_matches_on_normalised_name():
    rows = [_Client(1, "Honey Tribe"), _Client(3, "Riverdance")]
    # 'Honey Tribe' == 'honey-tribe' once normalised.
    assert atrium_tasks.resolve_client(rows, "honey-tribe", "Honey Tribe").id == 1
    # Sentinel's 'Riverdance' should still pick up Atrium's 'Riverdance RV' (unambiguous prefix).
    assert atrium_tasks.resolve_client(rows, "riverdance-rv", "Riverdance RV").id == 3


def test_resolve_client_refuses_to_guess_when_ambiguous():
    """Mislinking one client's work to another is worse than leaving it unlinked."""
    rows = [_Client(1, "Riverdance North"), _Client(2, "Riverdance South")]
    assert atrium_tasks.resolve_client(rows, "riverdance-rv", "Riverdance RV") is None
    # Duplicated names are equally unsafe.
    assert atrium_tasks.resolve_client([_Client(1, "Acme"), _Client(2, "Acme")], "acme", "Acme") is None
    # Nothing remotely similar, and an empty roster.
    assert atrium_tasks.resolve_client([_Client(1, "Totally Other")], "riverdance-rv", "Riverdance RV") is None
    assert atrium_tasks.resolve_client([], "riverdance-rv", "Riverdance RV") is None
    # A very short name must not prefix-match half the roster.
    assert atrium_tasks.resolve_client([_Client(1, "RV")], "riverdance-rv", "Riverdance RV") is None


def test_writes_get_a_longer_timeout_than_reads():
    """A move is a read-modify-write of a whole workspace JSON in GCS. The original 6s gave up
    while the write LANDED, so the card moved and the user was told it failed."""
    assert atrium_tasks._WRITE_TIMEOUT >= 30
    assert atrium_tasks._READ_TIMEOUT < atrium_tasks._WRITE_TIMEOUT


def test_unconfirmed_write_is_not_reported_as_a_failure(monkeypatch):
    """No answer != it didn't happen. Claiming failure on a write that landed invites a
    double-move, so the wording must send the user to refresh instead."""
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "https://portal.example",
                        raising=False)

    def _timeout(*a, **k):
        raise TimeoutError("slow")

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _timeout)
    ok, err = atrium_tasks.move_task("riverdance-rv", "tk_1", "todo")
    assert ok is False
    low = err.lower()
    assert "refresh" in low
    assert "couldn't reach" not in low and "failed" not in low


def test_bridge_imports_without_third_party_deps():
    """STDLIB ONLY. `import requests` here crashed every container on boot -- it is not in the
    image, and an optional bridge must never be able to take the app down at import time. Checks
    every module in the bridge: the shared transport (atrium_bridge) and both its callers."""
    import pathlib

    from app.services import atrium_watcher

    for mod in (atrium_bridge, atrium_tasks, atrium_watcher):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        for line in src.splitlines():
            stripped = line.strip()
            assert not stripped.startswith("import requests"), f"requests is NOT in requirements.txt ({mod.__name__})"
            assert not stripped.startswith("from requests"), f"requests is NOT in requirements.txt ({mod.__name__})"


def test_fetch_degrades_when_atrium_is_unreachable(monkeypatch):
    """An Atrium outage returns [] -- the board still renders Sentinel's own rows."""
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "https://portal.example",
                        raising=False)

    def _boom(*a, **k):
        raise atrium_bridge.urllib.error.URLError("down")

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _boom)
    assert atrium_tasks.fetch_tasks() == []
    ok, err = atrium_tasks.move_task("c", "tk_1", "todo")
    assert ok is False and err


# --- The write half: Sentinel edits an Atrium card without leaving its own board ---------------
# Added 2026-07-29, when the board stopped answering "open it in Atrium to view or edit". These
# pin the two things that make editing across the bridge safe: the field translation (Sentinel's
# names in, Atrium's names out, nothing invented) and the fail-CLOSED posture on every explicit act.


def test_detail_and_writes_report_failure_instead_of_degrading(monkeypatch):
    """Fail-SOFT is right for the board list and WRONG here: an empty drawer or a silently dropped
    edit is indistinguishable from a deleted card. Every one of these must hand back a reason."""
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "portal_login_url", "", raising=False)
    payload, err = atrium_tasks.fetch_task("c", "tk_1")
    assert payload == {} and err
    payload, err = atrium_tasks.edit_task("c", "tk_1", {"title": "x"})
    assert payload == {} and err
    ok, err = atrium_tasks.remove_task("c", "tk_1")
    assert ok is False and err
    payload, err = atrium_tasks.comment_task("c", "tk_1", "hi")
    assert payload == {} and err
    ok, err = atrium_tasks.resolve_change_request("c", "tk_1", "cm_1")
    assert ok is False and err


class _HTTPErr(Exception):
    """Raise an urllib HTTPError whose body reads back, the way a real response does."""

    @staticmethod
    def raiser(code, body):
        class _E(atrium_bridge.urllib.error.HTTPError):
            def __init__(self):
                super().__init__("u", code, "err", {}, None)

            def read(self):
                return body

        def _raise(*a, **k):
            raise _E()

        return _raise


def test_gone_is_a_distinct_answer_from_a_broken_bridge(monkeypatch):
    """Only Atrium's own 404 may reach the user as "that card is gone" -- the router keys its 404
    off these exact constants, so a timeout can never be reported as a deletion."""
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "https://portal.example",
                        raising=False)

    _404 = _HTTPErr.raiser(404, b'{"error":"not_found"}')
    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _404)
    assert atrium_tasks.fetch_task("c", "tk_1")[1] == atrium_tasks.GONE
    assert atrium_tasks.edit_task("c", "tk_1", {"title": "x"})[1] == atrium_tasks.GONE
    assert atrium_tasks.remove_task("c", "tk_1")[1] == atrium_tasks.GONE

    def _timeout(*a, **k):
        raise TimeoutError("slow")

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _timeout)
    assert atrium_tasks.edit_task("c", "tk_1", {"title": "x"})[1] != atrium_tasks.GONE


def test_a_404_from_an_undeployed_portal_is_not_a_deleted_card(monkeypatch):
    """Deploy order matters: ship Sentinel before the portal and these routes don't exist yet.
    Flask answers an unknown route with HTML (parses to nothing) while Atrium answers a real
    missing card with {"error": "not_found"} — telling those apart is the difference between
    "redeploy platform-dash" and someone hunting for a card nobody deleted."""
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "https://portal.example",
                        raising=False)

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen",
                        _HTTPErr.raiser(404, b"<!doctype html><h1>Not Found</h1>"))
    assert atrium_tasks.fetch_task("c", "tk_1")[1] == atrium_tasks.NOT_DEPLOYED

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen",
                        _HTTPErr.raiser(404, b'{"error":"not_found"}'))
    assert atrium_tasks.fetch_task("c", "tk_1")[1] == atrium_tasks.GONE


def test_field_translation_speaks_atriums_names_and_invents_nothing():
    import datetime

    out = atrium_tasks.to_atrium_fields({
        "title": "Rename me",
        "client_facing_notes": "the client reads this",
        "atrium_visible": True,
        "atrium_department": "acquisition",
        "atrium_lead_id": "leo@agora.ph",
        "due_date": datetime.date(2026, 9, 30),
        "assigned_to_id": 7,          # Sentinel-only: Atrium has no such concept
        "description": "ignored",      # Sentinel-only
        "maintasks": [{"id": "mt_1", "title": "Phase 1", "assignee_id": "leo@agora.ph",
                       "subs": [{"id": "st_1", "text": "Draft", "done": True}]}],
    })
    assert out["client_note"] == "the client reads this"      # the same idea under Atrium's name
    assert out["client_facing"] is True
    assert out["department"] == "acquisition" and out["lead_id"] == "leo@agora.ph"
    assert out["due_date"] == "2026-09-30"                    # json can't carry a date object
    assert "assigned_to_id" not in out and "description" not in out
    # Atrium's main tasks are keyed `text`, Sentinel's `title` -- the wire format is Atrium's.
    assert out["maintasks"][0]["text"] == "Phase 1"
    assert out["maintasks"][0]["subs"][0]["text"] == "Draft"


def test_clearing_a_field_sends_empty_not_null():
    """A cleared date/charge must reach Atrium as "", which is how workspace.py stores 'unset'."""
    out = atrium_tasks.to_atrium_fields({"due_date": None, "service_charge": None,
                                         "atrium_visible": None})
    assert out["due_date"] == "" and out["service_charge"] == ""
    assert out["client_facing"] is False


def test_atrium_only_update_fields_are_dropped_for_a_sentinel_row():
    """TaskUpdateIn carries fields the Sentinel branch of the update route must POP before
    setattr-ing onto the model. Every one has to be a real TaskUpdateIn field, or the pop is a no-op
    that silently protects nothing."""
    from app.schemas import TaskUpdateIn

    known = set(TaskUpdateIn.model_fields)
    for name in atrium_tasks.ONLY_ATRIUM:
        assert name in known, f"{name} is not a TaskUpdateIn field"


def test_start_date_is_no_longer_atrium_only():
    """🔴 2026-08-03 (M5): `tasks.start_date` exists now, so leaving it in ONLY_ATRIUM would drop
    the field on every Sentinel edit — saved-looking, never saved."""
    from app.models import Task

    assert "start_date" not in atrium_tasks.ONLY_ATRIUM
    assert hasattr(Task, "start_date")


def test_the_hold_fields_stay_atrium_only_even_though_sentinel_has_the_columns():
    """A deliberate exception, not an oversight. Sentinel gained `on_hold` / `hold_reason` with the
    park feature (M3), but a hold is THREE coupled fields (`+ resume_to`) and only `POST /{id}/park`
    sets all three. A PATCH could otherwise leave a card on hold with nothing remembering where it
    came from, so the Sentinel branch keeps dropping them."""
    from app.models import Task

    assert {"on_hold", "hold_reason"} <= set(atrium_tasks.ONLY_ATRIUM)
    assert hasattr(Task, "on_hold") and hasattr(Task, "resume_to")


def test_detail_maps_onto_the_shape_the_drawer_renders():
    envelope = {
        "task": {
            "atrium_id": "riverdance-rv:tk_9", "task_id": "tk_9", "client_key": "riverdance-rv",
            "client_name": "Riverdance RV", "title": "audit ads", "status": "In Progress",
            "priority": "Urgent", "client_facing": True, "department": "acquisition",
            "department_label": "Acquisition", "lead_id": "leo@agora.ph", "lead_name": "Leo",
            "support_ids": ["ian@100.digital"], "support_names": ["Ian"],
            "client_note": "client reads this", "internal_notes": "team only",
            "on_hold": True, "hold_reason": "waiting on assets", "open_changes": 1,
            "reporter": "client", "reporter_name": "Owner",
            "maintasks": [{"id": "mt_1", "text": "Phase 1", "assignee_id": "leo@agora.ph",
                           "assignee_name": "Leo", "subs": [
                               {"id": "st_1", "text": "Draft", "done": False,
                                "assignee_id": "", "assignee_name": "", "dod": "internal"}]}],
            "comments": [{"id": "cm_1", "sender": "client", "sender_name": "Owner",
                          "body": "please redo", "kind": "changes", "resolved": False,
                          "created_at": "2026-07-29T01:00:00Z"}],
            "history": [{"actor": "leo@agora.ph", "field": "created", "old": "", "new": "audit ads",
                         "at": "2026-07-28T01:00:00Z"},
                        {"actor": "leo@agora.ph", "field": "stage", "old": "todo",
                         "new": "in_progress", "at": "2026-07-29T01:00:00Z"}],
        },
        "roster": [{"id": "leo@agora.ph", "name": "Leo"}],
        "departments": [{"key": "acquisition", "label": "Acquisition"}],
    }
    d = atrium_tasks.as_task_detail(envelope)
    assert d["id"] == "atrium:riverdance-rv:tk_9" and d["source"] == "atrium"
    # The drawer's own field names, so one template renders both kinds of card.
    assert d["client_facing_notes"] == "client reads this"
    assert d["assigned_team_name"] == "Acquisition"
    assert d["maintasks"][0]["title"] == "Phase 1"          # text -> title
    assert d["maintasks"][0]["assignee"]["name"] == "Leo"   # resolved, not an email on screen
    assert d["comments"][0]["author"]["name"] == "Owner"
    assert d["comments"][0]["kind"] == "changes" and d["open_changes"] == 1
    # Activity reads newest-first here; Atrium keeps its history oldest-first.
    assert d["history"][0]["new_value"] == "in_progress"
    # The pickers travel with the card: Atrium's roster + departments, not Sentinel's.
    assert d["atrium_roster"] == [{"id": "leo@agora.ph", "name": "Leo"}]
    assert d["atrium_lead_name"] == "Leo" and d["atrium_support_names"] == ["Ian"]
    assert d["on_hold"] is True and d["hold_reason"] == "waiting on assets"
    # Sentinel-only concepts stay empty rather than being faked from an Atrium value.
    assert d["account_manager"] is None and d["description"] == ""
    # 🔴 CHANGED 2026-08-05: `assignee` now carries Atrium's LEAD as an ID-LESS person, because
    # hiding it made the board render owned client work as "Unassigned" while this very drawer said
    # "Lead: Leo". The rule was never "show nothing" — it is "never fake a Sentinel identity", and
    # that is `assigned_to_id`/`assignee.id` staying None, asserted right below.
    # See tests/test_atrium_card_owner.py.
    assert d["assignee"] == {"id": None, "name": "Leo", "profile_pic_url": None}
    assert d["assigned_to_id"] is None and d["assigned_team_id"] is None


def test_every_write_purpose_matches_the_route_it_signs(monkeypatch):
    """The HMAC purpose is per-endpoint on Atrium's side; a mismatch is a silent 401."""
    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "https://portal.example",
                        raising=False)
    seen = []

    def _fake_call(purpose, path, params=None, body=None, timeout=None):
        seen.append((purpose, path))
        return 200, {"task": {}, "comment": {}}

    monkeypatch.setattr(atrium_tasks, "_call", _fake_call)
    atrium_tasks.fetch_task("c", "tk_1")
    atrium_tasks.edit_task("c", "tk_1", {"title": "x"})
    atrium_tasks.remove_task("c", "tk_1")
    atrium_tasks.comment_task("c", "tk_1", "hi")
    atrium_tasks.resolve_change_request("c", "tk_1", "cm_1")
    assert seen == [
        ("task-detail", "/api/internal/task"),
        ("task-update", "/api/internal/task-update"),
        ("task-delete", "/api/internal/task-delete"),
        ("task-comment", "/api/internal/task-comment"),
        ("task-comment", "/api/internal/task-comment"),
    ]


def test_signed_request_carries_the_platform_hmac_headers(monkeypatch):
    """The bridge uses the SAME scheme as the other internal endpoints -- no new secret."""
    import hashlib
    import hmac as _hmac

    monkeypatch.setattr(atrium_bridge.settings, "platform_sso_secret", "s3cret", raising=False)
    monkeypatch.setattr(atrium_bridge.settings, "atrium_api_url", "https://portal.example",
                        raising=False)
    seen = {}

    class _Resp:
        status = 200

        def read(self):
            return b'{"ok": true, "tasks": []}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.headers)
        return _Resp()

    monkeypatch.setattr(atrium_bridge.urllib.request, "urlopen", _urlopen)
    atrium_tasks.fetch_tasks()
    assert seen["url"].endswith("/api/internal/tasks")
    # urllib title-cases header names.
    ts = seen["headers"]["X-academy-ts"]
    expected = _hmac.new(b"s3cret", f"tasks:{ts}".encode(), hashlib.sha256).hexdigest()
    assert seen["headers"]["X-academy-sig"] == expected
