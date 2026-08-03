/* /growth — a MANAGER's read-only view of one person's growth (?user=<id>).
 *
 * Your own growth hub is no longer a page of its own: it merged into the Overview on
 * 2026-08-03 (rings above the task board, ledger below it — see dashboard.js). This shell
 * survives for the one thing the Overview can't do, which is show somebody ELSE's profile.
 * Arriving here without a ?user is therefore a request for your own hub — send it to the
 * Overview rather than rendering a second, stale copy of it.
 */
window.pageInit = async (S) => {
  const userId = new URLSearchParams(location.search).get("user");
  if (!userId) { location.replace("/dashboard"); return; }
  await GrowthPanel.mount(S, S.view(), { userId, mast: true });
};
