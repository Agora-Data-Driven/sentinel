window.pageInit = async (S) => {
  const err = S.qs("#err");
  const showErr = (m) => { err.textContent = m; err.classList.add("show"); };

  // Surface Google callback errors (?error=...)
  const q = new URLSearchParams(location.search);
  if (q.get("error") === "noaccount") showErr("That Google account isn't registered. Ask an admin to add you first.");
  else if (q.get("error") === "google") showErr("Google sign-in failed. Please try again.");

  // Which methods are available?
  let cfg = { google_enabled: false, dev_login_enabled: false };
  try { cfg = await S.api("/api/auth/config"); } catch (e) {}

  /* The Agora portal is the ONE front door. When SSO is wired up, first try trading the portal's
     shared cookie for a session — someone already signed in there lands straight on the dashboard
     and never sees this page. Failing that, send them to the portal to sign in, with ?next= so
     they come back here.

     Two deliberate escape hatches, so nobody can ever be locked out of an internal tool by a
     portal outage or a misconfiguration: an explicit ?local=1, and dev login (which stays behind
     DEV_LOGIN_ENABLED and is off in production). */
  if (cfg.sso_enabled && q.get("local") !== "1" && !q.get("error")) {
    let ssoErr = null;
    try {
      await S.api("/api/auth/sso", { method: "POST" });
      location.replace("/dashboard");
      return;
    } catch (e) { ssoErr = e; }

    // 403 = a VALID portal login whose email isn't a user here. Bouncing to the portal would
    // return instantly (already signed in there) and loop forever, so stop and say so.
    if (ssoErr && ssoErr.status === 403) {
      showErr(ssoErr.detail || "Your portal account isn't registered in Sentinel.");
    } else if (cfg.portal_login_url) {
      // 401 = no portal session. Sending them to sign in is exactly right.
      const next = encodeURIComponent(location.origin + "/dashboard");
      location.replace(cfg.portal_login_url + (cfg.portal_login_url.includes("?") ? "&" : "?") + "next=" + next);
      return;
    }
  }
  if (!cfg.google_enabled) {
    const gw = S.qs("#google-wrap"); if (gw) gw.style.display = "none";  // hide until OAuth is configured
  }
  if (cfg.dev_login_enabled) {
    S.qs("#devwrap").style.display = "block";
    try {
      const users = await S.api("/api/auth/dev-users");
      S.qs("#user-select").innerHTML = users.map((u) => `<option value="${u.id}">${S.esc(u.name)} · ${S.esc(u.role.replace("_", " "))}</option>`).join("");
      S.qs("#devsignin").onclick = async () => {
        try { await S.api("/api/auth/dev-login", { method: "POST", body: { user_id: Number(S.qs("#user-select").value) } }); location.href = "/dashboard"; }
        catch (e) { showErr(e.detail || "Dev sign in failed"); }
      };
    } catch (e) {}
  }

  // Password login.
  S.qs("#login-form").onsubmit = async (e) => {
    e.preventDefault();
    err.classList.remove("show");
    const btn = S.qs("#signin"); btn.disabled = true; btn.textContent = "Signing in…";
    try {
      await S.api("/api/auth/login", { method: "POST", body: { email: S.qs("#email").value.trim(), password: S.qs("#password").value } });
      location.href = "/dashboard";
    } catch (e2) {
      showErr(e2.detail || "Invalid email or password");
      btn.disabled = false; btn.textContent = "Sign in";
    }
  };
};
