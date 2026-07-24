"""Optional internal-only service charge on tasks: normalized on write, shown in the detail view,
and NEVER included in the client-facing Atrium payload."""
from __future__ import annotations

import app.constants as C
from app.models import Task
from app.serializers import atrium_payload


def test_service_charge_is_optional_and_normalized(client, auth, make_user):
    auth(make_user(role=C.ROLE_ACCOUNT_MANAGER))

    # Omitted entirely -> no charge.
    r = client.post("/api/tasks", json={"title": "No charge"})
    assert r.status_code == 200, r.text
    assert r.json()["service_charge"] is None
    assert r.json()["service_charge_label"] is None

    # "$4,200" -> stored bare, displayed formatted.
    r = client.post("/api/tasks", json={"title": "Paid", "service_charge": "$4,200"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["service_charge"] == "4200"
    assert body["service_charge_label"] == "$4,200"

    # Blank and zero both mean "no charge".
    for junk in ("", "0", "abc"):
        r = client.post("/api/tasks", json={"title": f"j{junk}", "service_charge": junk})
        assert r.json()["service_charge"] is None, junk


def test_service_charge_editable_and_clearable(client, auth, make_user):
    auth(make_user(role=C.ROLE_ACCOUNT_MANAGER))
    tid = client.post("/api/tasks", json={"title": "T"}).json()["id"]

    assert client.patch(f"/api/tasks/{tid}", json={"service_charge": "1500.50"}).json()["service_charge"] == "1500.50"
    # Clearing it back to empty is allowed (optional field).
    assert client.patch(f"/api/tasks/{tid}", json={"service_charge": ""}).json()["service_charge"] is None


def test_service_charge_never_crosses_to_atrium(client, auth, make_user, db):
    auth(make_user(role=C.ROLE_ACCOUNT_MANAGER))
    tid = client.post("/api/tasks", json={"title": "Secret money", "service_charge": "9999"}).json()["id"]
    payload = atrium_payload(db.get(Task, tid), db)
    assert "service_charge" not in payload
    assert "9999" not in str(payload)
