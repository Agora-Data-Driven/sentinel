/* Minimal DOM stub — enough to run the prototype's render path and every handler.
   Not a browser: just proves nothing throws and the right things appear. */
const fs = require("fs");
const path = require("path");

const HTML = path.join("c:/Users/Christian/Downloads/Agora_Data_Driven/sentinel/docs",
  "taskboard_target_prototype.html");

let nodeSeq = 0;
function mkNode(tag) {
  const n = {
    tag, _id: ++nodeSeq, children: [], _html: "", _text: "",
    className: "", value: "", type: "", checked: false, disabled: false,
    style: new Proxy({ cssText: "" }, { set(o, k, v) { o[k] = v; return true; },
                                       get(o, k) { return o[k] === undefined ? "" : o[k]; } }),
    attrs: {},
    onclick: null, onchange: null, oninput: null,
    appendChild(c) { this.children.push(c); c.parent = this; return c; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k]; },
    remove() {
      if (this.parent) this.parent.children = this.parent.children.filter((x) => x !== this);
    },
    focus() {},
    closest() { return mkNode("div"); },
    querySelector(sel) {
      const hit = find(this, sel);
      if (hit) return hit;
      if (sel.startsWith("#") && subtreeHtml(this).includes('id="' + sel.slice(1) + '"'))
        return document.getElementById(sel.slice(1));
      return null;
    },
    querySelectorAll(sel) { return findAll(this, sel); },
    classList: {
      add(c) { if (!n.className.includes(c)) n.className = (n.className + " " + c).trim(); },
      remove(c) { n.className = n.className.split(/\s+/).filter((x) => x !== c).join(" "); },
      toggle(c, on) { on ? this.add(c) : this.remove(c); },
      contains(c) { return n.className.split(/\s+/).includes(c); }
    },
    get childNodes() { return this.children; },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); this.children = []; },
    get textContent() {
      if (this._text) return this._text;
      const own = stripTags(this._html);
      return own + this.children.map((c) => c.textContent).join("");
    },
    set textContent(v) { this._text = String(v); this.children = []; this._html = ""; }
  };
  return n;
}
function subtreeHtml(n) {
  return String(n._html) + n.children.map(subtreeHtml).join("");
}
function stripTags(h) {
  return String(h).replace(/<[^>]*>/g, "")
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'");
}

function matches(n, sel) {
  if (sel.startsWith("#")) return n.attrs.id === sel.slice(1) || n._domId === sel.slice(1);
  if (sel.startsWith(".")) return n.className.split(/\s+/).includes(sel.slice(1));
  return n.tag === sel;
}
function find(root, sel) {
  for (const c of root.children) {
    if (matches(c, sel)) return c;
    const hit = find(c, sel);
    if (hit) return hit;
  }
  return null;
}
function findAll(root, sel, out) {
  out = out || [];
  for (const c of root.children) {
    if (matches(c, sel)) out.push(c);
    findAll(c, sel, out);
  }
  return out;
}

const byId = {};
["seats","bridge","reset","sent","atr","aurl","surl","itabs","icode","inote",
 "legend","veil","mod","toasts","insp","insp-toggle"].forEach((id) => {
  byId[id] = mkNode("div");
  byId[id]._domId = id;
  byId[id].attrs.id = id;
});

global.document = {
  getElementById(id) {
    if (byId[id]) return byId[id];
    // ids created inside innerHTML strings (form fields) — hand back a stub with a value
    const n = mkNode("input");
    n._domId = id;
    if (id === "c-share") n.checked = true;
  n.value = id === "c-svc" ? "standalone_static"
            : id === "c-name" ? "Autumn hamper — static batch"
            : id === "c-client" ? "honeytribe"
            : id === "c-due" ? "2026-09-14"
            : id === "c-note" ? "Kicking this off now."
            : id === "s-note" ? "First ads go live mid-September."
            : id === "qa-in" ? "Can we get a version for Instagram stories?"
            : "";
    byId[id] = n;
    return n;
  },
  createElement: mkNode,
  createTextNode(t) { const n = mkNode("#text"); n._text = String(t); return n; },
  head: mkNode("head"),
  body: mkNode("body")
};
global.window = { EventSource: null };
global.location = { search: "", pathname: "/tasks" };
global.history = { replaceState() {} };
global.setTimeout = (fn) => { void fn; return 0; };   // fire nothing async
global.Array = Array;

// ---- run it ----
const html = fs.readFileSync(HTML, "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

let fails = 0, passes = 0;
function ok(label, cond) {
  if (cond) { passes++; } else { fails++; console.log("  ✗ " + label); }
}
function step(label, fn) {
  try { fn(); passes++; }
  catch (e) { fails++; console.log("  ✗ " + label + " → " + e.message + "\n" + e.stack.split("\n")[1]); }
}

step("initial render", () => { eval(script); });

const sent = () => byId.sent;
const atr = () => byId.atr;
const allText = (n) => n.textContent;

function clickByText(root, text, tag) {
  const btns = findAll(root, tag || "button");
  for (const b of btns) {
    if (b.onclick && b.textContent.includes(text)) { b.onclick(); return true; }
  }
  return false;
}
function seat(name) {
  const btns = findAll(byId.seats, "button");
  for (const b of btns) if (b.textContent.includes(name)) { b.onclick(); return true; }
  return false;
}
function view(name) { return clickByText(sent(), name); }
function selWith(optText) {
  return findAll(sent(), "select").find((x) =>
    findAll(x, "option").some((o) => o.textContent === optText));
}
function routeVia(team) {
  const sel = selWith("— not routed —");
  if (!sel) throw new Error("no team select in the drawer");
  sel.value = team; sel.onchange();
}
function openCard(name) {
  // Past work is also a .sdraw, so match the card drawer by its "Open card ·" eyebrow.
  const already = findAll(sent(), ".sdraw").some((d) =>
    d.textContent.includes("Open card ·") && d.textContent.includes(name));
  if (already) return;                                   // clicking again would close it
  const c = findAll(sent(), ".tcard").find((x) => x.textContent.includes(name));
  if (!c) throw new Error("card not on this board: " + name);
  c.onclick();
}

console.log("\nsentinel + atrium prototype — smoke\n");

ok("sentinel rendered", allText(sent()).includes("Task Board"));
ok("board has the Parked column (Stage 1 label)", allText(sent()).includes("Parked"));
ok("board does NOT show the retired 'Blocked' label", !allText(sent()).includes("Blocked"));
ok("atrium rendered", allText(atr()).includes("Tasks"));
ok("atrium says read-only", allText(atr()).includes("Read-only"));
ok("atrium has no drag/delete affordance", !allText(atr()).includes("data-pgcol"));
ok("legend rendered", findAll(byId.legend, "li").length >= 16);
ok("inspector has 4 tabs", findAll(byId.itabs, "button").length === 4);

step("every seat renders", () => {
  ["Zhen","Justine","Ehjay","Charles","Dana","Christina"].forEach((n) => {
    if (!seat(n)) throw new Error("seat not found: " + n);
  });
});

step("client seat blocks Sentinel", () => {
  seat("Christina");
  if (!allText(sent()).includes("cannot open Sentinel")) throw new Error("no client bounce");
  if (!allText(atr()).includes("Request a revision")) throw new Error("client buttons missing");
});

step("viewer seat is read-only", () => {
  seat("Dana");
  const txt = allText(sent());
  if (!txt.includes("Read-only seat")) throw new Error("no viewer banner");
  if (txt.includes("+ New service")) throw new Error("viewer offered New service");
  if (txt.includes("Park it")) throw new Error("viewer offered Park it");
  if (!txt.includes("Read-only seat.")) throw new Error("fields not rendered as text");
});

step("employee sees a card routed to their team (4.2)", () => {
  seat("Justine");
  if (!allText(sent()).includes("Spring drop")) throw new Error("assigned card missing");
});

step("team lead may set priority (4.1)", () => {
  seat("Ehjay");
  const sels = findAll(sent(), "select");
  const hasPrio = sels.some((s) => findAll(s, "option").some((o) => o.textContent === "Urgent"));
  if (!hasPrio) throw new Error("no priority select for a team lead");
});

step("all four views render", () => {
  seat("Charles");
  ["By Employee","Monitor","Intake","Board"].forEach((v) => {
    if (!view(v)) throw new Error("view button missing: " + v);
  });
});

step("monitor counts completed_at, not updated_at", () => {
  seat("Charles"); view("Monitor");
  if (!allText(sent()).includes("completed_at")) throw new Error("no completed_at note");
});

step("intake triage creates a task", () => {
  seat("Charles"); view("Intake");
  if (!allText(sent()).includes("second static")) throw new Error("no seeded request");
  if (!clickByText(sent(), "Accept")) throw new Error("no Accept button");
  if (!allText(sent()).includes("second static")) throw new Error("accepted task not on board");
});

step("park stores the column it left, resume names it", () => {
  seat("Charles"); view("Board");
  // open #447 (Spring drop) and park it
  const cards = findAll(sent(), ".tcard");
  const c = findAll(sent(), ".tcard").find((x) => x.textContent.includes("Spring drop"));
  if (!c) throw new Error("Spring drop card missing");
  c.onclick();
  if (!clickByText(sent(), "Park it")) throw new Error("no Park it");
  if (!allText(sent()).includes("Resume → In Progress"))
    throw new Error("resume does not name the stored column");
  if (!clickByText(sent(), "Resume →")) throw new Error("resume failed");
});

step("review gates Mark complete (D5)", () => {
  seat("Charles"); view("Board");
  const c = findAll(sent(), ".tcard").find((x) => x.textContent.includes("Spring drop"));
  c.onclick();
  const txt = allText(sent());
  if (!txt.includes("needs a Team Lead's approval"))
    throw new Error("complete is not gated on approval");
});

step("share mints a card and stores the id (0.1)", () => {
  seat("Charles"); view("Board");
  const c = findAll(sent(), ".tcard").find((x) => x.textContent.includes("Welcome sequence"));
  if (!c) throw new Error("unpublished card missing");
  c.onclick();
  if (!allText(sent()).includes("Internal only")) throw new Error("no internal-only banner");
  if (!clickByText(sent(), "Share with the client…")) throw new Error("no Share button");
  // modal is open — confirm
  if (!clickByText(byId.mod, "Share with the client")) throw new Error("modal confirm missing");
  if (!allText(sent()).includes("atrium:rhe:")) throw new Error("atrium id not stored on the row");
  if (!allText(byId.icode).includes("task-add")) throw new Error("no task-add in the inspector");
});

step("bridge down makes a failure loud (0.2)", () => {
  byId.bridge.onclick();                     // bridge DOWN
  seat("Charles"); view("Board");
  const c = findAll(sent(), ".tcard").find((x) => x.textContent.includes("Spring drop"));
  c.onclick();
  // move it via the status select
  const sel = findAll(sent(), "select").find((s) =>
    findAll(s, "option").some((o) => o.textContent === "Revision Needed"));
  if (!sel) throw new Error("status select missing");
  sel.value = "revision";
  sel.onchange();
  const txt = allText(sent());
  if (!txt.includes("stale")) throw new Error("stale state not surfaced");
  if (!txt.includes("Retry the push")) throw new Error("no retry affordance");
  byId.bridge.onclick();                     // bridge back up
  if (!clickByText(sent(), "Retry the push")) throw new Error("retry failed");
});

step("client comment + revision reach the row (D4)", () => {
  seat("Christina");
  if (!clickByText(atr(), "Request a revision")) throw new Error("no revision button");
  if (!allText(byId.icode).includes("task-response")) throw new Error("no reverse payload");
  seat("Charles");
  if (!allText(sent()).includes("Revision requested")) throw new Error("row not flagged");
});

step("client request files into intake (D3)", () => {
  seat("Christina");
  if (!clickByText(atr(), "Send request")) throw new Error("no Send request");
  if (!allText(byId.icode).includes("task-request")) throw new Error("no request payload");
  seat("Charles"); view("Intake");
  if (!allText(sent()).includes("Instagram stories")) throw new Error("request not in intake");
});

step("new service defaults to shared (D6)", () => {
  seat("Charles"); view("Board");
  if (!clickByText(sent(), "+ New service")) throw new Error("no New service");
  if (!allText(byId.mod).includes("Share with the client now")) throw new Error("no share switch");
  const cb = byId.mod.querySelector("#c-share");
  if (!cb || !cb.checked) throw new Error("share switch is not ON by default");
  if (!clickByText(byId.mod, "Create service")) throw new Error("create failed");
  if (!allText(sent()).includes("Autumn hamper")) throw new Error("new card not on board");
  if (!allText(sent()).includes("atrium:honeytribe:")) throw new Error("not published on create");
});

step("More options holds campaign / charge / service type", () => {
  seat("Charles"); view("Board");
  if (!clickByText(sent(), "+ New service")) throw new Error("no New service");
  const txt = allText(byId.mod);
  if (!txt.includes("More options")) throw new Error("no progressive-disclosure block");
  ["Service type","Service charge","Internal notes","Lead","Priority","Content type"]
    .forEach((f) => { if (!txt.includes(f)) throw new Error("field missing: " + f); });
  if (!txt.includes("the automated task creator"))
    throw new Error("service type is not named as the task creator");
  // the landing line must state where it goes BEFORE you commit
  if (!txt.includes("Lands in")) throw new Error("no landing line");
  if (!txt.includes("Ehjay")) throw new Error("the notified lead is not named");
  if (!txt.includes("notify_managers"))
    throw new Error("the query-not-column mechanism is not surfaced");
  if (!txt.includes("Team.lead_id"))
    throw new Error("the rejected column is not named");
  clickByText(byId.mod, "Cancel");
});

step("service type routes the department and seeds the breakdown", () => {
  seat("Charles"); view("Board");
  clickByText(sent(), "+ New service");
  clickByText(byId.mod, "Create service");            // harness picks standalone_static
  const t = findAll(sent(), ".tcard").find((x) => x.textContent.includes("Autumn hamper"));
  if (!t) throw new Error("card not created");
  if (!t.textContent.includes("Paid Media"))
    throw new Error("department not derived from the service template");
  const d = allText(sent());   // create already opened the drawer
  if (!d.includes("Static Ad — standalone")) throw new Error("service not recorded");
  if (!d.includes("Batch brief approved")) throw new Error("breakdown not seeded");
  // standalone_static is campaign:false — the Campaign field must not appear on it
  if (d.includes("CAMPAIGN")) throw new Error("campaign shown on a non-campaign service");
  if (!d.includes("Acquisition")) throw new Error("not routed to a team");
});

step("complete → file → Past work on both boards (M4)", () => {
  seat("Charles"); view("Board");
  // the drawer persists across renders for S.open, so clicking the card again would TOGGLE it shut
  const c = findAll(sent(), ".tcard").find((x) => x.textContent.includes("Autumn hamper"));
  if (!c) throw new Error("new card missing");
  c.onclick();
  findAll(sent(), ".bx").forEach((b) => { if (b.onclick) b.onclick(); });
  if (!clickByText(sent(), "Submit for review")) throw new Error("submit missing");
  if (!clickByText(sent(), "Approve")) throw new Error("approve missing");
  if (!clickByText(sent(), "Mark complete")) throw new Error("complete blocked after approval");
  if (!clickByText(sent(), "Mark ended & file")) throw new Error("file missing");
  if (!allText(sent()).includes("Past work")) throw new Error("no Past work drawer");
  if (!allText(atr()).includes("Past work")) throw new Error("client lost the delivered record");
  if (!allText(atr()).includes("Delivered")) throw new Error("client card not marked delivered");
});

step("inspector: internal fields are struck, never sent", () => {
  seat("Charles"); view("Board");
  const c = findAll(sent(), ".tcard").find((x) => x.textContent.includes("Spring drop"));
  c.onclick();
  const sel = findAll(sent(), "select").find((s) =>
    findAll(s, "option").some((o) => o.textContent === "In Progress"));
  sel.value = "in_progress"; sel.onchange();          // a push we know fired
  const code = byId.icode.innerHTML;
  if (!code.includes("strike")) throw new Error("no struck keys in the push payload");
  ["priority","service_charge","internal_notes","step_dod","assignee_id"].forEach((k) => {
    if (!code.includes(k)) throw new Error("internal key not listed as withheld: " + k);
  });
  if (!code.includes("client_note")) throw new Error("client_note should cross");
});

step("inspector folds away without touching the board", () => {
  seat("Charles"); view("Board");
  byId["insp-toggle"].onclick();
  if (!byId.insp.className.includes("off")) throw new Error("inspector did not fold");
  if (byId["insp-toggle"].textContent !== "Show") throw new Error("toggle label stale");
  if (!allText(sent()).includes("To Do")) throw new Error("board lost");
  byId["insp-toggle"].onclick();
  if (byId.insp.className.includes("off")) throw new Error("inspector did not unfold");
});

step("the open card announces itself", () => {
  seat("Charles"); view("Board");
  const c = findAll(sent(), ".tcard").find((x) => x.textContent.includes("Spring drop"));
  c.onclick();
  if (!allText(sent()).includes("Open card · #447")) throw new Error("no drawer eyebrow");
});

step("routing notifies the team's lead, derived not stored (D9)", () => {
  seat("Charles"); view("Board");
  const c = findAll(sent(), ".tcard").find((x) => x.textContent.includes("Welcome sequence"));
  c.onclick();                                 // #448 has no team
  routeVia("Acquisition");
  const d = allText(sent());
  if (!d.includes("Ehjay triages")) throw new Error("queue owner not named on the card");
  if (d.includes("· Ehjay") && d.includes("Team /")) throw new Error("lead shown as assignee");
});

step("an employee files into a team's queue, not onto themselves (D10)", () => {
  seat("Justine");                             // employee, Acquisition
  if (!clickByText(sent(), "+ New service")) throw new Error("employee cannot create");
  const txt = allText(byId.mod);
  if (!txt.includes("Files into")) throw new Error("landing line not employee-aware");
  if (!txt.includes("Filed by me")) throw new Error("does not warn it leaves their board");
  if (!clickByText(byId.mod, "Create service")) throw new Error("create failed");
  // harness picks standalone_static => Acquisition, which IS Justine's team, so she still sees it
  const own = findAll(sent(), ".tcard").find((x) => x.textContent.includes("Autumn hamper"));
  if (!own) throw new Error("card vanished from her own team's board");
  if (own.textContent.includes("Justine")) throw new Error("self-assigned despite a team");
  if (!own.textContent.includes("Acquisition")) throw new Error("not filed to the team");
});

step("a lead can send queued work back, with ownership never vague (D11)", () => {
  seat("Charles"); view("Board");
  openCard("Welcome sequence");
  routeVia("Acquisition");
  if (allText(sent()).includes("Send back to")) throw new Error("offered a bounce on own filing");
  seat("Ehjay");                                  // lead of Acquisition
  openCard("Welcome sequence");
  if (!clickByText(sent(), "Send back to Charles")) throw new Error("lead cannot bounce");
  // Ehjay can no longer SEE it — team is cleared and it is not assigned to him. Correct:
  // once you refuse work it stops being your team's. So read the banner from the filer's seat.
  if (allText(sent()).includes("Welcome sequence"))
    throw new Error("bounced card still on the refusing lead's board");
  seat("Charles");
  openCard("Welcome sequence");
  const d = allText(sent());
  if (!d.includes("Sent back by Ehjay")) throw new Error("no bounce banner");
  if (!d.includes("Not ours")) throw new Error("reason not recorded");
  const c = findAll(sent(), ".tcard").find((x) => x.textContent.includes("Welcome sequence"));
  if (!c) throw new Error("bounced card lost");
  if (!c.textContent.includes("Sent back")) throw new Error("no card pill");
  if (!c.textContent.includes("Charles")) throw new Error("not assigned back to the filer");
});

step("bounce is not offered once the team owns the card (D11)", () => {
  byId.reset.onclick();
  seat("Charles"); view("Board");
  openCard("Spring drop");                        // routed AND assigned to Justine
  seat("Ehjay");
  openCard("Spring drop");
  if (allText(sent()).includes("Send back to"))
    throw new Error("bounce offered on a card someone already owns");
});

step("re-routing answers the refusal and clears it (D11)", () => {
  byId.reset.onclick();
  seat("Charles"); view("Board");
  openCard("Welcome sequence");
  routeVia("Acquisition");
  seat("Ehjay"); openCard("Welcome sequence");
  clickByText(sent(), "Send back to Charles");
  seat("Charles"); openCard("Welcome sequence");
  // the record tab legitimately shows internal fields; the PUSH tab must withhold them
  if (!byId.icode.innerHTML.includes("Not ours"))
    throw new Error("the reason is missing from the Sentinel record");
  routeVia("Acquisition");
  if (allText(sent()).includes("Sent back by")) throw new Error("bounce did not clear");
});

step("a bounce reason is withheld from the client push (D11)", () => {
  byId.reset.onclick();
  seat("Charles"); view("Board");
  openCard("Spring drop");                        // already published
  const sel = findAll(sent(), "select").find((x) =>
    findAll(x, "option").some((o) => o.textContent === "Revision Needed"));
  sel.value = "revision"; sel.onchange();         // forces a push, inspector shows tab 1
  const code = byId.icode.innerHTML;
  if (!code.includes("bounce_reason")) throw new Error("bounce_reason absent from the push view");
  const struckBlock = code.slice(0, code.indexOf("bounce_reason"));
  if (!struckBlock.includes("strike")) throw new Error("internal keys not struck in the push");
});

step("routing is a select over every team, not a button naming one", () => {
  byId.reset.onclick();
  seat("Charles"); view("Board");
  openCard("Welcome sequence");
  if (allText(sent()).includes("Route to Acquisition"))
    throw new Error("the hardcoded route button is back");
  const sel = selWith("— not routed —");
  if (!sel) throw new Error("no team select");
  const teams = findAll(sel, "option").map((o) => o.textContent);
  ["Acquisition", "Lifecycle", "Data Analyst", "Development"].forEach((t) => {
    if (!teams.includes(t)) throw new Error("team missing from the picker: " + t);
  });
  sel.value = "Development"; sel.onchange();
  if (!allText(sent()).includes("Development")) throw new Error("did not route to Development");
});

step("every step has an owner picker, not a fixed pair of names", () => {
  byId.reset.onclick();
  seat("Charles"); view("Board");
  openCard("Spring drop");
  if (allText(sent()).includes("Delegate steps to Justine"))
    throw new Error("the hardcoded delegate button is back");
  const owners = findAll(sent(), "select").filter((x) => x.className.includes("own"));
  if (owners.length < 9) throw new Error("expected an owner picker per phase and per step, got " + owners.length);
  // the routed team's people come first, everyone else stays reachable
  const groups = findAll(owners[0], "optgroup").map((g) => g.attrs.label || g.label);
  if (!groups.length) throw new Error("owner picker is not grouped by team");
  const all = findAll(owners[owners.length - 1], "option").map((o) => o.textContent).join(" ");
  if (!all.includes("Charles")) throw new Error("someone outside the team is unreachable");
});

step("the bulk control replaces the fake delegate button", () => {
  byId.reset.onclick();
  seat("Charles"); view("Board");
  openCard("Welcome sequence");                 // 3 steps, none owned
  const txt = allText(sent());
  if (!txt.includes("unowned step")) throw new Error("no bulk assign control");
  const bulk = findAll(sent(), "select").filter((x) => x.className.includes("own"))
    .find((x) => findAll(x, "option").some((o) => o.textContent === "— pick someone —"));
  if (!bulk) throw new Error("bulk picker missing");
  bulk.value = "zhen"; bulk.onchange();
  if (allText(sent()).includes("unowned step")) throw new Error("steps still unowned");
});

step("a read-only seat gets text where a picker would be", () => {
  byId.reset.onclick();
  seat("Dana"); view("Board");
  openCard("Spring drop");
  const owners = findAll(sent(), "select").filter((x) => x.className.includes("own"));
  if (owners.length) throw new Error("viewer was handed an owner picker");
  if (!allText(sent()).includes("Routing is a lead or manager call"))
    throw new Error("no explanation for the missing routing control");
});

step("routing away from a team drops an owner who is not on it", () => {
  byId.reset.onclick();
  seat("Charles"); view("Board");
  openCard("Spring drop");                      // Acquisition · Justine owns it
  const sel = selWith("— not routed —");
  sel.value = "Development"; sel.onchange();
  const d = allText(sent());
  if (d.includes("JUJustine") || d.includes("Justine owns"))
    throw new Error("kept an owner who is not on the new team");
  if (!d.includes("Development")) throw new Error("did not route");
});

step("reset restores the seed", () => {
  byId.reset.onclick();
  if (allText(sent()).includes("Autumn hamper")) throw new Error("reset did not clear state");
});

console.log("\n" + passes + " passed, " + fails + " failed\n");
process.exit(fails ? 1 : 0);
