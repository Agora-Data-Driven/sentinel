/* Our North Star — embeds the self-contained "Who We Are · Agora Data Driven" manifesto
   (frontend/static/who-we-are.html) inside the app shell via an iframe, so it keeps its own
   designed dark theme + fonts while the Sentinel sidebar/topbar stay around it. */
window.pageInit = async (S) => {
  const view = S.view();
  S.qs("#top-sub").textContent = "Who we are, what we're building, and why";
  view.innerHTML = `
    <iframe src="/static/who-we-are.html?v=4" title="Who We Are · Agora Data Driven"
      style="width:100%;height:calc(100vh - 132px);min-height:560px;border:1px solid var(--line);
             border-radius:18px;box-shadow:var(--shadow);background:#06120E;display:block"
      loading="eager"></iframe>`;
};
