/* A Growth tab that IS a Mastery Engine, pinned to one program.
 *
 * The Philosophical and Spiritual tabs each embed the engine with ?program=<id> —
 * the engine reads the pin at boot and scopes its catalog, quizzes, decks and
 * roadmaps to that program (see PIN_PROGRAM in the engine's public/app.js). The
 * two pages differ by nothing but the program and copy, so ONE controller serves
 * both; each shell names its pin via <body data-program data-title data-sub>.
 *
 * Unlike the Professional tab there is no native dashboard or back button here:
 * the tab is the engine, full-frame, exactly like using it directly.
 */
window.pageInit = async (S) => {
  const view = S.view();
  const program = document.body.dataset.program || "";
  const label = document.body.dataset.title || "Engine";
  const sub = document.body.dataset.sub || "";
  if (sub) S.qs("#top-sub").textContent = sub;

  let cfg = null;
  try { cfg = await S.api("/api/academy/config"); } catch (e) { /* handled below */ }
  if (!cfg || !cfg.configured || !cfg.url) {
    view.innerHTML = `<div class="card" style="padding:28px;text-align:center">
      <h2 style="margin:0 0 8px">${S.esc(label)} is unavailable</h2>
      <p style="margin:0;color:var(--muted)">Couldn't reach the learning engine. Try again shortly.</p></div>`;
    return;
  }

  // cfg.url already ends in "?embed=1", so the pin appends with "&".
  view.innerHTML = `
    <iframe id="et-frame" title="AGORA Mastery Engine — ${S.esc(label)}" allow="microphone" loading="eager"
      style="width:100%;height:calc(100vh - 190px);min-height:520px;border:1px solid var(--line);
             border-radius:18px;box-shadow:var(--shadow);background:#fff;display:block"></iframe>`;
  S.qs("#et-frame").src = cfg.url + (program ? "&program=" + encodeURIComponent(program) : "");
};
