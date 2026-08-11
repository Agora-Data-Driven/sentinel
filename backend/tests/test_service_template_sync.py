"""Shipped services reach boards that already have services (WP 5.3, M6).

`main._seed_config` writes `service_templates` only when the table is EMPTY — true exactly once,
on a brand-new database. So adding a recipe to `SEED_TEMPLATES` used to reach nothing: every real
board already has rows, and the new service had to be retyped by hand in Manage per environment.
That is why the three standalone ad services existed in one dev database and nowhere else.

`sync_seed` closes it, and its safety is entirely in being INSERT-ONLY:

* an existing key is left alone — label / dept / recipe / defaults / is_active are all editable in
  Manage, and "correcting" them on boot would revert somebody's customisation on every deploy;
* a deliberately deleted service must stay deleted — Manage deletes softly (`is_active=False`) and
  an inactive row still counts as present here;
* so the only possible effect is giving a board a service it has never seen.
"""
from __future__ import annotations

import json

from app.models import ServiceTemplate
from app.services import task_templates


def _keys(db):
    return {r.key for r in db.query(ServiceTemplate).all()}


# --- the recipes themselves ---------------------------------------------------------------------

def test_the_three_standalone_ad_services_are_in_code():
    # They used to live only in one dev DB — that is the bug WP 5.3 fixes.
    for key in ("standalone_video", "standalone_static", "standalone_carousel"):
        assert key in task_templates.SEED_TEMPLATES, key
        assert task_templates.SEED_TEMPLATES[key]["dept"] == "Acquisition"


def test_standalone_ads_are_not_campaign_shaped():
    """Their content_type is the ad FORMAT, not "Campaign".

    🔴 This no longer governs whether the Campaign FIELD is offered — since 2026-08-11 that field is
    on every task, because §4 of the task-placement guidelines makes post-launch one-line work the
    main thing needing a campaign, and none of it is campaign-shaped (see taskboard.js). The content
    type still has to stay honest about what each recipe IS.
    """
    for key in ("standalone_video", "standalone_static", "standalone_carousel"):
        assert task_templates.SEED_TEMPLATES[key]["content_type"] != "Campaign"
    assert task_templates.SEED_TEMPLATES["google_meta_campaign"]["content_type"] == "Campaign"


def test_the_meta_campaign_recipe_keeps_content_creation_inside_the_campaign_card():
    """🔴 §2 of the task-placement guidelines: "all work required to build and launch that campaign
    should stay inside that campaign card." `google_meta_campaign` stops at Launch & verify, so the
    ads themselves had to be raised as separate standalone_* cards — the exact split those guidelines
    forbid. This recipe is the one that carries both phases."""
    tpl = task_templates.SEED_TEMPLATES["meta_campaign"]
    assert tpl["dept"] == "Acquisition"
    assert tpl["content_type"] == "Campaign"
    phases = [title for title, _ in tpl["groups"]]
    assert phases == ["Campaign build", "Content creation"], phases
    build, content = (subs for _, subs in tpl["groups"])
    # The launch step is what closes the card (§2: "once the campaign is launched, the Campaign Build
    # Task is considered complete") — it has to be IN the build phase, not a follow-up card.
    assert "Campaign launch" in build
    assert "Strategize content" in content


def test_the_two_campaign_recipes_are_distinct_keys():
    """🔴 `meta_campaign` is a NEW key rather than an edit to `google_meta_campaign`, and it has to
    stay one. `sync_seed` is insert-only, so rewriting the older recipe would reach no existing
    board — production included — and would live only in this file. Retiring the older one is a
    Manage → Services decision (a soft delete this sync respects forever), not a code change."""
    assert "google_meta_campaign" in task_templates.SEED_TEMPLATES
    assert "meta_campaign" in task_templates.SEED_TEMPLATES
    assert (task_templates.SEED_TEMPLATES["meta_campaign"]["groups"]
            != task_templates.SEED_TEMPLATES["google_meta_campaign"]["groups"])


def test_every_shipped_recipe_has_at_least_one_step():
    for key, tpl in task_templates.SEED_TEMPLATES.items():
        assert tpl["groups"], key
        for title, subs in tpl["groups"]:
            assert title and subs, key


# --- sync_seed ------------------------------------------------------------------------------------

def _drop(db, *keys):
    """Simulate a board that predates those services (the conftest seeds a complete one)."""
    for key in keys:
        db.query(ServiceTemplate).filter(ServiceTemplate.key == key).delete()
    db.commit()


def test_sync_adds_shipped_services_to_a_board_that_already_has_some(db):
    # 🔴 The bug in one line: this table is NOT empty, so `_seed_config`'s own
    # "only when the table is empty" branch skips it and the new services never arrive.
    _drop(db, "standalone_video", "standalone_static", "standalone_carousel")
    assert _keys(db) and "standalone_video" not in _keys(db)

    added = task_templates.sync_seed(db)

    assert set(added) == {"standalone_video", "standalone_static", "standalone_carousel"}
    assert _keys(db) == set(task_templates.SEED_TEMPLATES)


def test_sync_never_overwrites_an_existing_row(db):
    """A board's Manage edits must survive every deploy."""
    row = db.query(ServiceTemplate).filter(ServiceTemplate.key == "website_fix").one()
    row.label = "OUR OWN NAME"
    row.dept = "Custom Team"
    row.content_type = "Bespoke"
    row.default_priority = "Urgent"
    row.maintasks_json = json.dumps([{"title": "Ours"}])
    db.commit()

    task_templates.sync_seed(db)

    db.refresh(row)
    assert row.label == "OUR OWN NAME"
    assert row.dept == "Custom Team"
    assert row.content_type == "Bespoke"
    assert row.default_priority == "Urgent"
    assert json.loads(row.maintasks_json) == [{"title": "Ours"}]


def test_a_deliberately_deleted_service_is_not_resurrected(db):
    """Manage deletes softly. An inactive row still counts as present, or every deploy would undo
    the deletion and the service would reappear in the picker forever."""
    row = db.query(ServiceTemplate).filter(ServiceTemplate.key == "website_fix").one()
    row.is_active = False
    db.commit()

    added = task_templates.sync_seed(db)

    assert "website_fix" not in added
    assert db.query(ServiceTemplate).filter(ServiceTemplate.key == "website_fix").count() == 1
    db.refresh(row)
    assert row.is_active is False


def test_sync_fills_a_completely_empty_board(db):
    db.query(ServiceTemplate).delete()
    db.commit()
    assert task_templates.sync_seed(db)
    assert _keys(db) == set(task_templates.SEED_TEMPLATES)


def test_sync_is_idempotent(db):
    # It runs on EVERY boot; a pass that writes anything on an already-synced board would mean
    # churn on every deploy. The conftest already seeded, so this must be a no-op immediately.
    assert task_templates.sync_seed(db) == []
    assert task_templates.sync_seed(db) == []


def test_sync_seeds_a_usable_recipe(db, make_user):
    task_templates.sync_seed(db)
    steps = task_templates.maintasks_for(db, "standalone_video")
    assert steps and steps[0]["subs"], "the seeded recipe must produce a real breakdown"
