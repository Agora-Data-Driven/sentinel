"""Guards on the three costs that made the task board slow (2026-08-07).

Performance work rots silently — a helpful-looking `db.get(...)` added to `task_card` next year puts
back a query per card and nothing fails. So the properties are pinned here as behaviour:

1. `GET /api/tasks` runs a BOUNDED number of queries — the count must not grow with the board.
2. A card built WITHOUT a prefetch is byte-identical to one built with it (the cache is an
   optimisation, never a source of truth).
3. `maintasks.normalized` memoizes per row, and stops memoizing the moment the row changes.
4. The Atrium board-list cache reuses a SUCCESS, refuses to cache a FAILURE, and is dropped by
   any write.

Why each number matters is in `serializers.CardPrefetch`, `maintasks.normalized` and the block
comment above `atrium_tasks.fetch_tasks`. Measured before this work: 801 cards → 2,946 queries.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import event

from app import constants as C
from app.database import engine
from app.models import Client, Task, TaskComment, TaskSupporter
from app.serializers import CardPrefetch, task_card
from app.services import atrium_tasks
from app.services import maintasks as MT


class _Counter:
    """Counts statements executed on the shared engine for the duration of a `with` block."""

    def __init__(self) -> None:
        self.n = 0

    def _bump(self, *_a, **_k) -> None:
        self.n += 1

    def __enter__(self) -> "_Counter":
        event.listen(engine, "before_cursor_execute", self._bump)
        return self

    def __exit__(self, *_exc) -> None:
        event.remove(engine, "before_cursor_execute", self._bump)


def _breakdown(owner_id: int) -> str:
    return MT.dumps([{"title": "Build", "assignee_id": owner_id,
                      "subs": [{"text": f"step {i}", "done": i % 2 == 0,
                                "assignee_id": owner_id} for i in range(4)]}])


def _make_board(db, n, *, lead, supporter, client_row):
    """`n` tasks, each with a client, a creator, a supporter, a breakdown and a comment — i.e. every
    field `task_card` has to resolve. A board of bare rows would not exercise the problem."""
    made = []
    for i in range(n):
        t = Task(title=f"Task {i}", status="To Do", priority="Medium", client_id=client_row.id,
                 assigned_to_id=lead.id, created_by_id=lead.id,
                 maintasks_json=_breakdown(lead.id))
        db.add(t)
        db.flush()
        db.add(TaskSupporter(task_id=t.id, user_id=supporter.id, added_by_id=lead.id))
        db.add(TaskComment(task_id=t.id, author_id=lead.id, body="looks good",
                           attachments_json='[{"name": "brief.pdf"}]'))
        made.append(t)
    db.commit()
    return made


# --- 1. the board's query count does not grow with the board ------------------------------------

def test_board_query_count_is_bounded_not_per_card(client, auth, make_user, db):
    """🔴 THE regression guard. `task_card` used to cost ~3.7 queries PER CARD — a lazy comment
    count, plus `db.get` for the client/assignee/creator defeated by SQLAlchemy's WEAK identity map
    (the same four clients cost 703 SELECTs on an 800-card board). Ten cards and fifty cards must
    cost the same handful of queries."""
    admin = auth(make_user(C.ROLE_ADMIN))
    helper = make_user(C.ROLE_EMPLOYEE)
    row = Client(name="Acme", atrium_client_id="acme")
    db.add(row)
    db.commit()

    _make_board(db, 10, lead=admin, supporter=helper, client_row=row)
    with _Counter() as small:
        assert len(client.get("/api/tasks").json()) == 10

    _make_board(db, 40, lead=admin, supporter=helper, client_row=row)
    with _Counter() as big:
        assert len(client.get("/api/tasks").json()) == 50

    # Five times the cards must not mean five times the queries. The allowance is deliberately loose
    # (auth, vocab and the prefetch itself are all in here) — what it forbids is PER-CARD growth.
    assert big.n <= small.n + 2, (
        f"{small.n} queries for 10 cards but {big.n} for 50 — something reads per card again. "
        "See serializers.CardPrefetch.")


def test_prefetch_batches_are_chunked_for_sqlite_parameter_limits(db, make_user):
    """Every `IN (...)` in the prefetch is chunked, because SQLite caps bound parameters per
    statement (999 before 3.32). A board big enough to exceed that must SLOW DOWN, never raise."""
    lead = make_user(C.ROLE_ADMIN)
    tasks = []
    for i in range(450):                      # > one 400-wide chunk, so the loop really iterates
        t = Task(title=f"T{i}", status="To Do", priority="Medium", created_by_id=lead.id)
        db.add(t)
        tasks.append(t)
    db.commit()
    pre = CardPrefetch.for_tasks(db, tasks)
    assert len(pre.counts) == 450


# --- 2. the cache is an optimisation, never a source of truth ------------------------------------

def test_a_card_is_identical_with_and_without_a_prefetch(client, auth, make_user, db):
    """`task_detail` and `people.py`'s profile card go through `task_card` too. If the prefetched
    path could ever disagree with the direct one, the board and the drawer would show different
    facts about the same row — which is the bug class this codebase keeps re-fixing."""
    admin = auth(make_user(C.ROLE_ADMIN))
    helper = make_user(C.ROLE_EMPLOYEE)
    row = Client(name="Acme", atrium_client_id="acme")
    db.add(row)
    db.commit()
    (task,) = _make_board(db, 1, lead=admin, supporter=helper, client_row=row)

    with_pre = task_card(task, db, viewer=admin, pre=CardPrefetch.for_tasks(db, [task]))
    without = task_card(task, db, viewer=admin)
    assert with_pre == without
    # And the fields the prefetch is responsible for are actually populated, so this isn't two
    # copies of the same emptiness.
    assert with_pre["comment_count"] == 1
    assert with_pre["attachment_count"] == 1
    assert with_pre["client_name"] == "Acme"
    assert with_pre["assignee"]["id"] == admin.id
    assert [s["id"] for s in with_pre["support"]] == [helper.id]


def test_a_card_with_no_comments_reports_zero_not_a_fallback(db, make_user):
    """`counts` distinguishes "prefetched, and there are none" from "not prefetched". A task with no
    comments must be a cache HIT at 0, not fall through to a lazy load."""
    lead = make_user(C.ROLE_ADMIN)
    t = Task(title="Quiet", status="To Do", priority="Medium", created_by_id=lead.id)
    db.add(t)
    db.commit()
    pre = CardPrefetch.for_tasks(db, [t])
    with _Counter() as counted:
        assert pre.comment_counts(t) == (0, 0)
    assert counted.n == 0


# --- 3. the memoized breakdown ------------------------------------------------------------------

def test_normalized_is_memoized_per_row(db, make_user):
    lead = make_user(C.ROLE_ADMIN)
    t = Task(title="T", status="To Do", priority="Medium", maintasks_json=_breakdown(lead.id))
    db.add(t)
    db.commit()
    first = MT.normalized(t)
    assert MT.normalized(t) is first, "the second call must reuse the parse, not repeat it"


def test_normalized_re_parses_after_the_breakdown_changes(db, make_user):
    """🔴 The memo is keyed on the identity of the raw string, so a WRITE has to miss it. If it did
    not, an edit would render against the pre-edit breakdown — a lost save, in exchange for a parse."""
    lead = make_user(C.ROLE_ADMIN)
    t = Task(title="T", status="To Do", priority="Medium", maintasks_json=_breakdown(lead.id))
    db.add(t)
    db.commit()
    before = MT.normalized(t)
    assert len(before[0]["subs"]) == 4

    t.maintasks_json = MT.dumps([{"title": "Build", "subs": [{"text": "only one"}]}])
    after = MT.normalized(t)
    assert after is not before
    assert [s["text"] for s in after[0]["subs"]] == ["only one"]


def test_normalized_matches_normalize(db, make_user):
    """The memo must not change the ANSWER — only how often it is computed."""
    lead = make_user(C.ROLE_ADMIN)
    t = Task(title="T", status="To Do", priority="Medium", maintasks_json=_breakdown(lead.id))
    db.add(t)
    db.commit()
    memoized = MT.normalized(t)
    direct = MT.normalize(t.maintasks_json, t.checklist_json)
    # Ids are minted per call for steps that arrive without one; everything else must agree.
    assert [(m["title"], [(s["text"], s["done"], s["assignee_id"]) for s in m["subs"]])
            for m in memoized] == \
           [(m["title"], [(s["text"], s["done"], s["assignee_id"]) for s in m["subs"]])
            for m in direct]


# --- 4. the Atrium board-list cache -------------------------------------------------------------

@pytest.fixture
def bridge_on(monkeypatch):
    """Configure the bridge so `fetch_tasks` really reaches `atrium_bridge.call`."""
    from app.config import settings
    monkeypatch.setattr(settings, "platform_sso_secret", "test-secret", raising=False)
    monkeypatch.setattr(settings, "atrium_api_url", "https://portal.example", raising=False)
    monkeypatch.setattr(settings, "atrium_cache_seconds", 60, raising=False)


def test_a_successful_read_is_reused_within_the_ttl(bridge_on):
    card = {"client_key": "acme", "task_id": "t1", "text": "Launch"}
    with patch("app.services.atrium_tasks._call",
               return_value=(200, {"tasks": [card]})) as called:
        assert atrium_tasks.fetch_tasks() == [card]
        assert atrium_tasks.fetch_tasks() == [card]
    assert called.call_count == 1, "the second board load must not spend another round trip"


def test_a_failure_is_never_cached(bridge_on):
    """🔴 Caching the fail-soft `[]` would turn one blip into every client card vanishing from the
    board for the whole TTL. A failure must be retried on the very next request."""
    with patch("app.services.atrium_tasks._call", return_value=(0, {})) as called:
        assert atrium_tasks.fetch_tasks() == []
        assert atrium_tasks.fetch_tasks() == []
    assert called.call_count == 2


def test_a_malformed_body_is_never_cached(bridge_on):
    with patch("app.services.atrium_tasks._call",
               return_value=(200, {"tasks": "not-a-list"})) as called:
        assert atrium_tasks.fetch_tasks() == []
        assert atrium_tasks.fetch_tasks() == []
    assert called.call_count == 2


def test_the_cache_is_keyed_by_client(bridge_on):
    with patch("app.services.atrium_tasks._call",
               return_value=(200, {"tasks": []})) as called:
        atrium_tasks.fetch_tasks()
        atrium_tasks.fetch_tasks("acme")
    assert called.call_count == 2, "a one-client read is a different question from the whole estate"


@pytest.mark.parametrize("write", [
    lambda: atrium_tasks.move_task("acme", "t1", "in_progress"),
    lambda: atrium_tasks.add_task("acme", "New card"),
    lambda: atrium_tasks.edit_task("acme", "t1", {"title": "Renamed"}),
    lambda: atrium_tasks.remove_task("acme", "t1"),
    lambda: atrium_tasks.comment_task("acme", "t1", "hello"),
    lambda: atrium_tasks.resolve_change_request("acme", "t1", "c1"),
])
def test_every_write_invalidates_the_cache(bridge_on, write):
    """🔴 Otherwise editing a client card and landing back on the board shows the pre-edit copy,
    which is indistinguishable from the save having been dropped. Each write is listed because the
    invalidation lives in each one — a NEW write function will fail this parametrisation until it is
    added, which is the point."""
    fresh = {"client_key": "acme", "task_id": "t1", "text": "Launch"}
    with patch("app.services.atrium_tasks._call", return_value=(200, {"tasks": [fresh],
                                                                     "task": {}, "comment": {}})):
        atrium_tasks.fetch_tasks()                       # warm it
        write()
        with patch("app.services.atrium_tasks._call",
                   return_value=(200, {"tasks": []})) as after:
            atrium_tasks.fetch_tasks()
    assert after.call_count == 1, "the write left a stale board list in place"


def test_zero_seconds_disables_the_cache(bridge_on, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "atrium_cache_seconds", 0, raising=False)
    with patch("app.services.atrium_tasks._call", return_value=(200, {"tasks": []})) as called:
        atrium_tasks.fetch_tasks()
        atrium_tasks.fetch_tasks()
    assert called.call_count == 2
