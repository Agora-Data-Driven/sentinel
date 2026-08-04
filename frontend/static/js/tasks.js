/* Task Board page — the board's own home again since 2026-08-03 (decision D7 of
   sentinel/docs/TASKBOARD_REBUILD.md). It was embedded in the dashboard from 2026-07-26 until then;
   `main.dashboard_page` forwards `/dashboard?open=<id>` here so the notifications minted in that
   window still land on their card.

   This page is deliberately THIN: every behaviour lives in taskboard.js as a mountable component
   (`TaskBoard.mount(S, root)`), because the same board also has to render inside the dashboard's
   "my work" strip context and inside whatever surface comes next. The page's only jobs are to give
   it a full-width root and to say so when it fails. */
window.pageInit = async (S) => {
  const view = S.view();
  view.innerHTML = `<div id="tb-page"></div>`;
  if (!window.TaskBoard) {
    view.innerHTML = `<div class="empty card pad" style="margin-top:30px">
      Couldn't load the task board component. Try a refresh.</div>`;
    return;
  }
  try {
    await TaskBoard.mount(S, S.qs("#tb-page"), { page: true });
  } catch (e) {
    S.toast(e.detail || "Couldn't load the task board", "err");
  }
};
