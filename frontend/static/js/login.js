/* 🔴 THE ONE-BOUNCE GUARD — the loop-breaker of last resort.

   Sending someone to the portal is only ever correct ONCE. If we arrive back here still without a
   session, the portal could not give us a usable cookie, and bouncing again produces the exact
   ping-pong that stranded people for a whole morning (portal answers an already-signed-in visitor
   with a bare redirect; see atrium's login() for the other half). Suppressing a bounce that follows
   a bounce within seconds turns an infinite loop into one wasted round trip plus a working form.

   Deliberately a TIMESTAMP, not a flag: a legitimate bounce hours later in the same tab must still
   work, and a flag would strand that tab on the password form forever. sessionStorage (per tab, so
   one broken tab never speaks for another) and every access is wrapped — it throws outright in some
   privacy modes, and the loop-breaker must never be the thing that breaks the page. */
const BOUNCE_AT = "sentinel:sso-bounce-at";
const BOUNCE_WINDOW_MS = 20000;  // a loop iteration is ~1s; a human retry is not
const bouncedJustNow = () => {
  try { return Date.now() - Number(sessionStorage.getItem(BOUNCE_AT) || 0) < BOUNCE_WINDOW_MS; }
  catch (e) { return false; }
};
const markBounce = () => { try { sessionStorage.setItem(BOUNCE_AT, String(Date.now())); } catch (e) {} };

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

     THREE deliberate escape hatches, so nobody can ever be locked out of an internal tool by a
     portal outage or a misconfiguration: an explicit ?local=1, the one-bounce guard below, and dev
     login (which stays behind DEV_LOGIN_ENABLED and is off in production). */
  if (cfg.sso_enabled && q.get("local") !== "1" && !q.get("error") && !bouncedJustNow()) {
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
      /* 401 = no portal session. Sending them to sign in is exactly right.

         🔴 ?next= POINTS AT /login, NOT /dashboard. Only `/login` mints a Sentinel session out of a
         portal cookie (main.login_page); /dashboard merely AUTHENTICATES against `ag_sso` per
         request. Landing there meant nobody coming through the portal ever got a
         `sentinel_session` — the whole company rode the portal cookie, so every one of its 12h
         expiries put them back on this page needing another round trip. Via /login they get the
         normal week-long session and this path stops being a daily event. */
      markBounce();
      const next = encodeURIComponent(location.origin + "/login");
      location.replace(cfg.portal_login_url + (cfg.portal_login_url.includes("?") ? "&" : "?") + "next=" + next);
      return;
    }
  }
  // Say why the form is showing after a bounce — silence here is what made the loop unreadable. It
  // never CLOBBERS a message already on screen: a ?error= from the Google callback is more specific.
  if (bouncedJustNow() && !err.classList.contains("show")) {
    showErr("The portal couldn't sign you in to Sentinel. Sign in with your password below, or try the portal again.");
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

  // Password login. The form also posts natively to `POST /login` when this handler never runs —
  // see login.html. Here we preventDefault and use the API, so the page never reloads on a typo.
  const form = S.qs("#login-form");
  form.onsubmit = async (e) => {
    e.preventDefault();
    err.classList.remove("show");
    const btn = S.qs("#signin"); btn.disabled = true; btn.textContent = "Signing in…";
    try {
      await S.api("/api/auth/login", { method: "POST", body: { email: S.qs("#email").value.trim(), password: S.qs("#password").value } });
      location.href = "/dashboard";
    } catch (e2) {
      // A request that never reached the server (offline, a dead proxy) is not a bad password, and
      // must not read as one — hand it to the form's own native post rather than accusing the user.
      if (e2 && e2.status === undefined) { form.submit(); return; }
      showErr(e2.detail || "Invalid email or password");
      btn.disabled = false; btn.textContent = "Sign in";
    }
  };
};
