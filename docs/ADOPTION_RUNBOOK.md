# Runbook — finishing WP 3.4 (adoption) and 0.3 (stale shares)

> Everything in the taskboard rebuild is **built**. These two are the only things left, and they are
> left because they are **judgement over live client data**, not because anyone ran out of time.
> Plan and decisions: [TASKBOARD_REBUILD.md](TASKBOARD_REBUILD.md) — §4 (why), §5.4 (summary).

You need: a **super-admin** login on production Sentinel (admin is deliberately not enough) and
about 20 minutes of attention per client. Nothing here is irreversible except step 5, and step 5 has
an undo.

---

## 0. 🔴 Deploy first — this order is load-bearing

Two things that must be live **before** you adopt anything:

| what | why it has to be first |
|---|---|
| **WP 4.3** (de-duplication) | Without it every adopted card renders **twice** — once as its new Sentinel row, once as the bridge's copy of the same card — and the two diverge the moment anybody moves one. |
| **WP 1.2** (Blocked → Parked) | The rename runs as a boot-time sweep. Adopting first is harmless, but you'd be reading a plan whose statuses don't match the board you're about to look at. |

```powershell
cd C:\Users\Christian\Downloads\Agora_Data_Driven\sentinel
.\deploy\deploy.ps1
```

**Never a raw `gcloud run deploy`** — it wipes `PLATFORM_SSO_SECRET` and the portal/mastery URLs
(AGENTS.md §1). Then confirm what is actually serving, and read the **whole** traffic array — a
tagged old revision can sit at `traffic[0]`:

```powershell
gcloud run services describe sentinel --project agora-data-driven `
  --region asia-southeast1 --format="yaml(status.traffic)"
```

Sanity check that the rename landed (the board should say **Parked**, not Blocked) before going on.

---

## 1. Get a session

Open **https://sentinel-585951669065.asia-southeast1.run.app** and sign in as
`info@agoradatadriven.com`.

**Then stay in that tab and use DevTools → Console for everything below.** That is the whole trick:
the cookies are already attached, so you never copy a credential anywhere, and the CSRF header is
one line. Paste this helper in first:

```js
// Sends the CSRF token the way the app does. Safe to re-paste at any point.
const csrf = document.cookie.match(/sentinel_csrf=([^;]+)/)[1];
const S = async (path, body, method) => {
  const r = await fetch(path, {
    method: method || (body ? "POST" : "GET"),
    headers: { "content-type": "application/json", "X-CSRF-Token": csrf },
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.json();
  if (!r.ok) throw new Error(`${r.status}: ${JSON.stringify(j)}`);
  return j;
};
```

Who may call what — worth knowing before you read a 403 as a bug:

| endpoints | role |
|---|---|
| `/api/manage/*` (step 2) and `/api/tasks/adoption/*` (steps 3–5) | **super-admin only** — admin is deliberately not enough for adoption |
| `/api/tasks/atrium/stale-shares` + `atrium-clear-share` (step 6) | account manager and up |

---

## 2. List the workspaces and check they are linked

```js
const clients = await S("/api/manage/clients");
console.table(clients.map(c => ({ id: c.id, name: c.name, atrium_key: c.atrium_client_id })));
```

🔴 **A blank `atrium_key` must be fixed before that client is adopted.** Rows created for an unlinked
workspace carry `client_id = NULL`, cannot be attributed to a workspace, and so cannot be
de-duplicated against their own Atrium card — every one of their cards would show twice.
`apply()` refuses them for exactly this reason, and the error names the fix.

To link one (the key is the **Atrium workspace key**, e.g. `the-contract-shop`, not the dashboard
stack key `tcs` — those diverge for every client):

```js
await S("/api/manage/clients/7", { atrium_client_id: "the-contract-shop" }, "PATCH");
```

### The live mapping (read off both systems 2026-08-04)

Atrium's workspace keys, from `GET /api/internal/watcher/channels` (cross-workspace), against
Sentinel's client rows. 🔴 Note `rooming-house-expert` is **singular** and `riverdance-rv` carries the
`-rv` — the portal key never equals the dashboard stack key, and guessing it is how the proxy 502'd
for every client once before (atrium/AGENTS.md).

| Sentinel id | Sentinel client | Atrium workspace key |
|---|---|---|
| 1 | Honey Tribe | `honey-tribe` |
| 2 | Melo Yelo | `melo-yelo` |
| 3 | Riverdance | `riverdance-rv` |
| 4 | Rooming House Experts | `rooming-house-expert` |
| 5 | TCS | `the-contract-shop` |
| 6 | Super Cashflow | `super-cash-flow` |

`ian-fernandez` is Atrium's own house workspace (`workspace.HOUSE_CLIENT`, where the shared Watcher
archives live). It is nobody's client and must NOT be linked to one.

🔴 **Link all six, not just the two with cards to adopt.** The de-duplication is keyed on this field,
so an unlinked client's cards double the moment anything is shared to it — the WP 4.3 fix simply
cannot see a row it can't attribute to a workspace.

```js
for (const [id, key] of [[1,"honey-tribe"],[2,"melo-yelo"],[3,"riverdance-rv"],
                         [4,"rooming-house-expert"],[5,"the-contract-shop"],[6,"super-cash-flow"]]) {
  console.log(id, (await S(`/api/manage/clients/${id}`, {atrium_client_id: key}, "PATCH")).atrium_client_id);
}
```

---

## 3. Read the plan — this writes nothing

One client at a time. `plan()` and `apply()` are **different endpoints** on purpose; there is no
`dry_run` flag anywhere to get wrong.

```js
const plan = await S("/api/tasks/adoption/plan?client=the-contract-shop");
console.log(plan.counts, "linked:", plan.client_linked);
console.table(plan.adopt);   // what will be created
console.table(plan.skip);    // every skip, with its reason
```

**Read both tables.** What to look for:

| you see | what it means | what to do |
|---|---|---|
| `client_linked: false` | step 2 isn't done for this client | link it, re-run the plan |
| skip: *Already adopted* | a Sentinel row already claims that card | nothing — correct |
| skip: *Its status has no matching Sentinel column* | the card sits in a column this board doesn't have | add or rename the status in **Manage → Task Fields**, re-run |
| skip: *The card has no Atrium id* | malformed card | leave it; adopting it would create an unlinkable row |
| an `adopt` row that is clearly finished/abandoned work | adoption imports it as live work | delete or complete it in Atrium first, then re-run |

---

### What is actually out there (2026-08-04)

`GET /api/internal/tasks` over the HMAC bridge returns **4 Atrium cards in total**, in two
workspaces — so adoption is a ten-minute job, not a migration:

| workspace | cards |
|---|---|
| `melo-yelo` | New CRM creation · Qcard Google ads campaign – draft · Re-launch Qcard campaign |
| `super-cash-flow` | Rooming House Extension campaign |

🔴 That last one belongs to **Super Cashflow**, not to the "Rooming House Experts" client — it is a
title coincidence. Linking RHE to `super-cash-flow` because the words match would put one client's
card on another client's books.

The other four clients have no Atrium-origin cards, so their plans come back empty. Link them
anyway (above): the link is what keeps *future* shares from doubling.

## 4. Decide

The question for each `adopt` row is only: **is this still real work we are delivering?** If the
plan is mostly stale cards, clean them up in Atrium first — adoption is not the place to triage.

---

## 5. Apply — the one step that writes

```js
const key = "the-contract-shop";
const out = await S("/api/tasks/adoption/apply", { client: key, confirm: key });
console.log("BATCH:", out.batch, out.counts);
console.table(out.created);
```

`confirm` must repeat the client key exactly — not ceremony, it is the difference between "I read
the plan" and "I posted the wrong body".

### 🔴 Write the batch id down. It is the only handle on the run.

Then **open the board and look at it** before touching the next client. You are checking:

- every adopted card appears **once** (if any appears twice, stop — step 0 didn't deploy);
- they are in the columns the plan said;
- they show up for the managers who need them (they arrive unowned and unrouted, which is why they
  sit on every manager's board until somebody takes them).

### Undo

```js
await S("/api/tasks/adoption/revert", { batch: "adopt-the-contract-shop-1234567890" });
```

Removes exactly that run. It **refuses any row worked on since** — a comment, an assignment, a move,
a completion — and reports them as `kept` with the reason. That refusal is the feature: undoing
those would destroy real work. Nothing was ever written to Atrium, so the worst case of a bad run is
orphaned Sentinel rows, never damaged client-visible data.

**Then repeat 3 → 5 for the next client.** One at a time is the point, not a limitation.

---

## 6. WP 0.3 — reconcile the stale shares

Separate job, do it whenever. These are rows that claim `atrium_visible = True` but point at a card
**that was never created** — the lie the Send-to-Atrium fix uncovered on 2026-08-03.

```js
const stale = await S("/api/tasks/atrium/stale-shares");
console.table(stale);
```

There is deliberately **no bulk publish** (decision D15). These are live client records: some are
months old, some were delivered long ago. Publishing them all would put finished work back in front
of a client as though it were pending. Per row, exactly one of:

- **the work is still live** → open the card and Send to Atrium properly (it really publishes now);
- **it isn't** → clear the false claim, telling nobody:

```js
await S(`/api/tasks/${TASK_ID}/atrium-clear-share`, {});
```

Neither answer is derivable from the data. That is the whole reason this is a person's job.

---

## If something looks wrong

| symptom | cause |
|---|---|
| every adopted card appears twice | WP 4.3 isn't deployed — check the serving revision, don't debug the data |
| `400 … is not linked to a Sentinel client` | step 2 for that client |
| `403` on a POST | the `X-CSRF-Token` header — re-paste the helper in step 1 |
| `403` on a GET | you're not signed in as **super-admin**; admin is not enough here |
| a card vanished from the board | 🔴 stop and say so. Hiding work is the one failure mode this system guards hardest against (AGENTS.md §5); it should not be possible, and it is worth a bug report rather than a workaround. |
