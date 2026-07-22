// Reading & Philosophy — the company canon (required books/philosophies), each merged with the
// worker's own status + reflection. Admins curate the canon; everyone tracks their progress. The
// coach sees what you're reading and your reflections.
window.pageInit = async (S) => {
  const view = S.view();
  const esc = S.esc;
  const api = S.api;
  const isAdmin = S.can("admin");
  const STATUSES = [{ v: "not_started", t: "Not started" }, { v: "reading", t: "Reading" }, { v: "done", t: "Done" }];

  let items = [];

  async function load() {
    view.innerHTML = S.skeleton ? S.skeleton({ rows: 5 }) : "Loading…";
    try { items = (await api("/api/development/reading")).items || []; }
    catch (e) { view.innerHTML = `<div class="empty card pad">${esc(e.detail || "Couldn't load.")}</div>`; return; }
    render();
  }

  function card(it) {
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
          ${STATUSES.map((s) => `<button class="seg-b ${s.v === st ? "on" : ""}" data-set="${s.v}" style="border:none;padding:6px 14px;font:600 12px Inter,sans-serif;cursor:pointer;background:${s.v === st ? "var(--violet-d)" : "transparent"};color:${s.v === st ? "#fff" : "var(--sub)"}">${s.t}</button>`).join("")}
        </div>
        <label class="field"><span>My reflection</span><textarea data-reflect="${it.id}" rows="3" placeholder="What stuck with you?">${esc(it.progress.reflection || "")}</textarea></label>
        <div class="row" style="justify-content:flex-end"><button class="btn sm primary" data-savereflect="${it.id}">Save reflection</button></div>
      </div></div>`;
  }

  function render() {
    view.innerHTML = `
      <div class="pagehead"><div>
        <h2>Reading &amp; Philosophy</h2>
        <div class="lead">The ideas everyone here should absorb. Track what you've read and reflect.</div>
      </div>${isAdmin ? `<button class="btn primary" id="add-canon">${S.ICON.plus}Add to canon</button>` : ""}</div>
      ${items.length ? items.map(card).join("") : '<div class="empty card pad">The canon is empty.' + (isAdmin ? " Add the first book or philosophy." : "") + "</div>"}`;
    wire();
  }

  function wire() {
    S.qsa(".seg").forEach((seg) => {
      const id = seg.dataset.status;
      seg.querySelectorAll("[data-set]").forEach((b) => b.onclick = async () => {
        try { await api(`/api/development/reading/${id}/progress`, { method: "PUT", body: { status: b.dataset.set } });
          const it = items.find((x) => x.id == id); if (it) it.progress.status = b.dataset.set; render();
        } catch (e) { S.toast(e.detail || "Couldn't update", "err"); }
      });
    });
    S.qsa("[data-savereflect]").forEach((b) => b.onclick = async () => {
      const id = b.dataset.savereflect;
      const val = S.qs(`[data-reflect="${id}"]`).value;
      try { await api(`/api/development/reading/${id}/progress`, { method: "PUT", body: { reflection: val } }); S.toast("Saved", "ok"); }
      catch (e) { S.toast(e.detail || "Couldn't save", "err"); }
    });

    if (!isAdmin) return;
    const add = S.qs("#add-canon"); if (add) add.onclick = () => canonForm();
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
        <label class="field"><span>Title</span><input id="c-title" value="${esc(it ? it.title : "")}" placeholder="e.g. Deep Work"></label>
        <label class="field"><span>Author</span><input id="c-author" value="${esc(it && it.author || "")}" placeholder="e.g. Cal Newport"></label>
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
        title: S.qs("#c-title").value.trim(),
        author: S.qs("#c-author").value.trim() || null,
        kind: S.qs("#c-kind").value,
        url: S.qs("#c-url").value.trim() || null,
        summary: S.qs("#c-summary").value.trim() || null,
        required: S.qs("#c-required").checked,
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
