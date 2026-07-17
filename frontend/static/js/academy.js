/* Academy — embeds the AGORA Mastery Engine (the team's learning app) inside the Sentinel shell.

   Same pattern as Our North Star: an iframe carrying its own designed UI while the Sentinel
   sidebar/topbar stay around it. The engine is asked for `?embed=1` so it drops its own header and
   Sentinel supplies the chrome.

   There is NO second sign-in: the engine reads the same portal `ag_sso` cookie this page was
   authenticated with. That works because both hosts live under agoradatadriven.com, so the cookie
   is same-site and rides along into the frame. If the engine ever moves off that domain the cookie
   stops arriving and it would render its own login inside the frame — which is why the backend
   reports `same_site` and we warn instead of silently showing a login box. */
window.pageInit = async (S) => {
  const view = S.view();
  S.qs("#top-sub").textContent = "Build your skills — quizzes, flashcards, and your progress";

  const panel = (title, body) => `
    <div class="card" style="padding:28px;text-align:center">
      <h2 style="margin:0 0 8px">${title}</h2>
      <p style="margin:0;color:var(--muted)">${body}</p>
    </div>`;

  let cfg;
  try {
    cfg = await S.api("/api/academy/config");
  } catch (e) {
    view.innerHTML = panel("Academy is unavailable", "Couldn't reach the learning engine. Try again shortly.");
    return;
  }

  if (!cfg || !cfg.configured) {
    view.innerHTML = panel(
      "Academy isn't configured yet",
      "The mastery engine URL is not set on this deployment (SKILL_MASTERY_URL).",
    );
    return;
  }

  const warn = cfg.same_site ? "" : `
    <div class="card" style="padding:12px 14px;margin-bottom:12px;border-color:#c9a227;background:#fffbe9">
      <strong>Heads up:</strong> the learning engine isn't on an agoradatadriven.com address, so the
      shared sign-in can't reach it and it may ask you to log in again inside the frame.
    </div>`;

  view.innerHTML = `${warn}
    <iframe src="${cfg.url}" title="AGORA Mastery Engine"
      style="width:100%;height:calc(100vh - 132px);min-height:560px;border:1px solid var(--line);
             border-radius:18px;box-shadow:var(--shadow);background:#fff;display:block"
      allow="microphone"
      loading="eager"></iframe>`;
};
