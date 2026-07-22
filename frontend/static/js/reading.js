// Reading & Philosophy — personal-growth/philosophy learning. Same Mastery Engine as Academy, just a
// different SUBJECT: any program tagged category="growth" shows here (its own curriculum + knowledge
// graph, kept separate from career programs). Plus the reading CANON — the books/philosophies that are
// the assigned source material. The holistic Coach is what bridges the two worlds (analogies between
// what you study and what you read); the graphs themselves stay separate.
window.pageInit = async (S) => {
  const view = S.view();
  const esc = S.esc;
  const api = S.api;
  const isAdmin = S.can("admin");
  const STATUSES = [{ v: "not_started", t: "Not started" }, { v: "reading", t: "Reading" }, { v: "done", t: "Done" }];

  let items = [];   // reading canon
  let ac = {};      // /api/academy/courses (programs + engine urls)

  const growthPrograms = () => (ac.programs || []).filter((p) => (p.category || "career") === "growth");
  const ringColor = (p) => (p >= 80 ? "#2E7D32" : p >= 50 ? "#C9A227" : "#B3261E");
  const ring = (pct) => {
    const p = Math.max(0, Math.min(100, Math.round(pct || 0)));
    return `<div class="rp-ring" style="background:conic-gradient(${ringColor(p)} ${p * 3.6}deg, var(--line) 0deg)"><span>${p}<i>%</i></span></div>`;
  };

  async function load() {
    view.innerHTML = S.skeleton ? S.skeleton({ rows: 5 }) : "Loading…";
    const [reading, courses] = await Promise.all([
      api("/api/development/reading").catch(() => ({ items: [] })),
      api("/api/academy/courses").catch(() => ({ programs: [], engineUrl: "" })),
    ]);
    items = reading.items || [];
    ac = courses || {};
    render();
  }

  function programCard(p) {
    return `<button class="rp-prog" data-program="${esc(p.id)}" title="Study ${esc(p.name)}">
      ${ring(p.pct)}
      <div class="rp-pinfo"><div class="rp-pname">${esc(p.name)}</div>
        <div class="rp-psub">${p.courseCount || 0} courses &middot; ${p.topicsPracticed || 0}/${p.topicsTotal || 0} topics practised</div></div>
      <span class="rp-open">Study &rarr;</span></button>`;
  }

  function canonCard(it) {
    const st = it.progress.status || "not_started";
    return `<div class="card" data-item="${it.id}" style="margin-bottom:14px">
      <div class="card-head">
        <h3>${S.ICON.book}${esc(it.title)} ${it.required ? '<span class="pill amber" style="font-size:11px">required</span>' : ""}</h3>
        ${isAdmin ? `<div class="row"><a href="#" class="linky" data-edit="${it.id}">edit</a><a href="#" class="linky danger" data-del="${it.id}">delete</a></div>` : ""}
      </div>
      <div class="card-body">
        <div class="sub" style="margin-bottom:6px">${esc(it.author || "")}${it.author ? " · " : ""}<span class="pill">${esc(it.kind)}</span>${it.url ? ` · <a href="${esc(it.url)}" target="_blank" rel="noopener" class="linky">link</a>` : ""}</div>
        ${it.summary ? `<div class="prewrap" style="margin-bottom:10px">${esc(it.summary)}</div>` : ""}
        <div class="seg" data-status="${it.id}" style="display:inline-flex;border:1px solid var(--line);border-radius:99px;overflow:hidden;margin-bottom:10px">
          ${STATUSES.map((s) => `<button class="seg-b" data-set="${s.v}" style="border:none;padding:6px 14px;font:600 12px Inter,sans-serif;cursor:pointer;background:${s.v === st ? "var(--violet-d)" : "transparent"};color:${s.v === st ? "#fff" : "var(--sub)"}">${s.t}</button>`).join("")}
        </div>
        <label class="field"><span>My reflection</span><textarea data-reflect="${it.id}" rows="3" placeholder="What stuck with you?">${esc(it.progress.reflection || "")}</textarea></label>
        <div class="row" style="justify-content:flex-end"><button class="btn sm primary" data-savereflect="${it.id}">Save reflection</button></div>
      </div></div>`;
  }

  function render() {
    const progs = growthPrograms();
    view.innerHTML = `
      <style>
        .rp-h { font-size:15px; text-transform:uppercase; letter-spacing:.5px; color:var(--muted); margin:0 0 12px; }
        .rp-progs { display:grid; gap:12px; margin-bottom:26px; max-width:900px; }
        .rp-prog { display:flex; align-items:center; gap:16px; width:100%; text-align:left; cursor:pointer;
          background:var(--card,#fff); border:1px solid var(--line); border-radius:16px; padding:14px 16px; font:inherit; color:inherit;
          transition: box-shadow .15s, transform .05s; }
        .rp-prog:hover { box-shadow: var(--shadow); } .rp-prog:active { transform: translateY(1px); }
        .rp-ring { width:52px; height:52px; border-radius:50%; flex:none; display:grid; place-items:center; position:relative; }
        .rp-ring::after { content:""; position:absolute; width:38px; height:38px; border-radius:50%; background:var(--card,#fff); }
        .rp-ring span { position:relative; z-index:1; font-weight:800; font-size:13px; } .rp-ring i { font-style:normal; font-size:9px; opacity:.7; }
        .rp-pinfo { flex:1; min-width:0; } .rp-pname { font-weight:700; font-size:15px; }
        .rp-psub { color:var(--muted); font-size:13px; margin-top:2px; } .rp-open { color:var(--violet-d); font-weight:700; font-size:13px; }
        #rp-engine { display:none; } #rp-engine.on { display:block; }
      </style>

      <div id="rp-dash">
        <div class="pagehead"><div>
          <h2>Reading &amp; Philosophy</h2>
          <div class="lead">Grow the person, not just the engineer — the ideas everyone here should absorb.</div>
        </div>${isAdmin && ac.adminUrl ? `<button class="btn ghost" id="rp-admin">Manage in admin</button>` : ""}</div>

        ${progs.length
          ? `<h2 class="rp-h">Study</h2><div class="rp-progs">${progs.map(programCard).join("")}</div>`
          : (isAdmin
              ? `<div class="card pad" style="margin-bottom:26px"><strong>No philosophy program yet.</strong>
                   <div class="sub" style="margin-top:6px">Create one in the Academy admin (Subject → <em>Personal growth / philosophy</em>), enrol people, and it appears here — same engine, separate subject.</div></div>`
              : "")}

        <div class="row between" style="align-items:baseline;margin-bottom:12px">
          <h2 class="rp-h" style="margin:0">Reading list</h2>
          ${isAdmin ? `<button class="btn sm primary" id="rp-add-canon">${S.ICON.plus}Add to canon</button>` : ""}
        </div>
        ${items.length ? items.map(canonCard).join("") : `<div class="empty card pad">The canon is empty.${isAdmin ? " Add the first book or philosophy." : ""}</div>`}
      </div>

      <div id="rp-engine">
        <button class="btn ghost" id="rp-back" style="margin-bottom:12px">&larr; Back to reading</button>
        <iframe id="rp-frame" title="Philosophy program" allow="microphone" loading="eager"
          style="width:100%;height:calc(100vh - 190px);min-height:520px;border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);background:#fff;display:block"></iframe>
      </div>`;
    wire();
  }

  function wire() {
    const dash = S.qs("#rp-dash"), engine = S.qs("#rp-engine"), frame = S.qs("#rp-frame");
    const openFrame = (url) => { frame.src = url; dash.style.display = "none"; engine.classList.add("on"); };
    S.qs("#rp-back").onclick = () => { engine.classList.remove("on"); dash.style.display = ""; frame.src = "about:blank"; };
    S.qsa(".rp-prog").forEach((b) => b.onclick = () => {
      if (!ac.engineUrl) return S.toast("Learning engine not configured", "err");
      openFrame(ac.engineUrl + "&home=quiz&program=" + encodeURIComponent(b.dataset.program));
    });
    const adminBtn = S.qs("#rp-admin"); if (adminBtn) adminBtn.onclick = () => { if (ac.adminUrl) openFrame(ac.adminUrl); };

    // Canon: per-item status + reflection.
    S.qsa(".seg").forEach((seg) => {
      const id = seg.dataset.status;
      seg.querySelectorAll("[data-set]").forEach((b) => b.onclick = async () => {
        try { await api(`/api/development/reading/${id}/progress`, { method: "PUT", body: { status: b.dataset.set } });
          const it = items.find((x) => x.id == id); if (it) it.progress.status = b.dataset.set; render();
        } catch (e) { S.toast(e.detail || "Couldn't update", "err"); }
      });
    });
    S.qsa("[data-savereflect]").forEach((b) => b.onclick = async () => {
      const id = b.dataset.savereflect, val = S.qs(`[data-reflect="${id}"]`).value;
      try { await api(`/api/development/reading/${id}/progress`, { method: "PUT", body: { reflection: val } }); S.toast("Saved", "ok"); }
      catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
    });

    if (!isAdmin) return;
    const add = S.qs("#rp-add-canon"); if (add) add.onclick = () => canonForm();
    S.qsa("[data-edit]").forEach((a) => a.onclick = (e) => { e.preventDefault(); canonForm(items.find((x) => x.id == a.dataset.edit)); });
    S.qsa("[data-del]").forEach((a) => a.onclick = async (e) => {
      e.preventDefault();
      try { await api(`/api/development/reading/canon/${a.dataset.del}`, { method: "DELETE" }); load(); }
      catch (err) { S.toast(err.detail || "Couldn't delete", "err"); }
    });
  }

  function canonForm(it) {
    const kinds = [{ v: "book", t: "Book" }, { v: "philosophy", t: "Philosophy" }, { v: "essay", t: "Essay" }];
    const m = S.modal({
      title: it ? "Edit canon item" : "Add to canon",
      body: `<div class="formgrid">
        <label class="field"><span>Title</span><input id="c-title" value="${esc(it ? it.title : "")}" placeholder="e.g. Meditations"></label>
        <label class="field"><span>Author</span><input id="c-author" value="${esc(it && it.author || "")}" placeholder="e.g. Marcus Aurelius"></label>
        <label class="field"><span>Kind</span><select id="c-kind">${kinds.map((k) => `<option value="${k.v}" ${it && it.kind === k.v ? "selected" : ""}>${k.t}</option>`).join("")}</select></label>
        <label class="field"><span>Link (optional)</span><input id="c-url" value="${esc(it && it.url || "")}" placeholder="https://…"></label>
        <label class="field"><span>Why it matters</span><textarea id="c-summary" rows="3">${esc(it && it.summary || "")}</textarea></label>
        <label class="field row" style="align-items:center;gap:8px"><input id="c-required" type="checkbox" style="width:auto" ${!it || it.required ? "checked" : ""}><span>Required reading</span></label>
      </div>`,
      footer: `<button class="btn ghost" id="c-cancel">Cancel</button><button class="btn primary" id="c-save">Save</button>`,
    });
    S.qs("#c-cancel").onclick = m.close;
    S.qs("#c-save").onclick = async () => {
      const body = {
        title: S.qs("#c-title").value.trim(), author: S.qs("#c-author").value.trim() || null,
        kind: S.qs("#c-kind").value, url: S.qs("#c-url").value.trim() || null,
        summary: S.qs("#c-summary").value.trim() || null, required: S.qs("#c-required").checked,
      };
      if (!body.title) return S.toast("Title is required", "err");
      try {
        if (it) await api(`/api/development/reading/canon/${it.id}`, { method: "PATCH", body });
        else await api("/api/development/reading/canon", { method: "POST", body });
        m.close(); load();
      } catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
    };
  }

  load();
};
