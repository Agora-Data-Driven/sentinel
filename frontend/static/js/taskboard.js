/* TaskBoard — the full Kanban (Board / By Employee / Monitor), formerly the /tasks page,
   now a mountable component embedded in the dashboard: TaskBoard.mount(S, containerEl, opts).
   Deep links (?open=<id> from notifications, ?new=1 from the command palette, ?view=…) are
   read from the CURRENT page URL, so they work at /dashboard; the old /tasks URL 302s there.

   `opts.scope` (and the `setScope` handle mount resolves to) is the Overview's PAGE-WIDE people
   filter, driven by the admin Team-progress table above: `{ ids: [userId…], order: [userId…] }`.
   An empty `ids` means no scoping at all. It is applied on top of this board's own filters, never
   instead of them — the two are different questions ("which client's work" vs "whose work"), and
   a page-level scope silently overriding a filter the user set here would be a lie about what
   they're looking at. */
window.TaskBoard = {
  async mount(S, root, opts) {
  const options = opts || {};
  // The page-wide scope. Cards are matched CLIENT-SIDE against it rather than through
  // ?assignee_id=: the API takes one assignee, this takes a set, and the list is already
  // permission-filtered by the server (task_perms.can_view) before it gets here — so narrowing it
  // further in the browser can only ever hide, never reveal.
  let scope = normaliseScope(options.scope);
  function normaliseScope(s) {
    const ids = (s && Array.isArray(s.ids) ? s.ids : []).map(Number).filter((n) => Number.isFinite(n));
    // `scoped`, NOT `ids.length`, decides whether to filter. A filter that matched nobody and no
    // filter at all both arrive with an empty list, and treating those the same would answer
    // "show me the stalled people" with the whole team's work.
    return { ids, set: new Set(ids), order: (s && s.order) || [], scoped: !!(s && s.scoped) };
  }
  // 🔴 The read-only seat (decision D8). `S.can()` is RANK-based and a viewer sits at the floor, so
  // every rank check already refuses it — but rank cannot express "sees everything, writes nothing",
  // so the seat is named explicitly here exactly as it is server-side (constants.VIEW_ALL_ROLES).
  // The server enforces all of this; hiding the controls is so a viewer is not offered buttons that
  // can only ever answer 403.
  const readOnly = S.user.role === "viewer";
  const canCreate = !readOnly;              // all other staff can add + edit tasks (internal tool)
  const canManage = S.can("account_manager"); // AM+ only: the Atrium bridge
  // Monitor is a READ, and monitoring is the viewer's entire purpose — so it is a rank check OR the
  // seat, matching `employee_summary`'s guard.
  const canMonitor = S.can("team_lead") || readOnly;
  // 🔴 PRIORITY: the server has always let a team lead set it within their own team
  // (task_perms.can_prioritize), and this file gated on `isAM` — so a lead saw a read-only value and
  // had to ask an AM to change a number they are trusted to own (§2.4f). The server was right; this
  // was the bug. `isAM` survives ONLY for Atrium-owned cards, where the server really is AM+
  // (can_manage_atrium): such a card has no Sentinel team for a lead to be the lead OF.
  const isAM = canManage;
  // 🔴 A TEAM LEAD'S POWERS FOLLOW WHAT THEY CAN SEE (2026-08-14, task_perms._lead_may_act).
  //
  // These four gates used to repeat the server's OLD rule — `t.assigned_team_id === S.user.team_id`
  // — and that mirror is precisely why the bug was reported as "Team Lead can't assign / can't
  // approve" rather than as a permission error: the picker rendered `disabled` and Approve was never
  // drawn, so nobody ever saw the 403 that would have explained it. A card with no department, an
  // adopted client card, work the lead raised for another team, and a lead whose own profile had no
  // department all produced the same dead card.
  //
  // The board only ever RECEIVES cards the server's `can_view` already let through, so mirroring
  // "anything they can see" is simply `isLead` — there is no client-side re-derivation left to drift
  // from the server. That is the point: the previous mirror was a second copy of a rule, and it
  // outlived the rule it copied.
  const isLead = !readOnly && S.can("team_lead");
  const canPrioritize = (t) => t.source === "atrium" ? canManage : (canManage || isLead);
  // On the create/edit FORM there may be no team yet (it is a field on the form), so this mirrors
  // create_task's `may_delegate` instead: a lead may set priority on work they raise.
  const canPrioritizeOnForm = canManage || canMonitor;
  // Mirrors task_perms.can_delete (the server enforces it): AM+ anywhere, team lead in their
  // team, and the creator for their own tasks. Drives the ✕ on cards + Delete in the drawer.
  // An Atrium-owned card (t.source === "atrium") has no assignee, team or creator tag to test, so
  // it follows task_perms.can_manage_atrium instead: managers only, since deleting it removes a
  // client's card (into Atrium's Bin, restorable for 30 days).
  const canDelete = (t) => readOnly ? false : (t.source === "atrium" ? canManage : (canManage
    || (canMonitor && t.assigned_team_id != null && t.assigned_team_id === S.user.team_id)
    || (t.created_by_id != null && t.created_by_id === S.user.id)));
  // Mirrors task_perms.can_review (the server enforces it): AM+ anywhere, a team lead within their
  // own team. Deciding a review is a management call; ASKING for one is not (that's can_edit).
  // Atrium-owned cards have no review state — there is no local row to hold one.
  // Mirrors task_perms.can_reassign (the server enforces it): delegation — changing the team or
  // an owner to SOMEBODY ELSE — is AM+ anywhere, a team lead within their own team. Used by the
  // D12 routing control; self-assignment is deliberately NOT gated on this, which is why the
  // per-step pickers stay open to everyone (§2.4e / WP 4.2f).
  const canReassign = (t) => !readOnly && (canManage || (t.source !== "atrium" && isLead));
  const canReview = (t) => !readOnly && t.source !== "atrium" && (canManage || isLead);
  // 🔴 MAY THIS VIEWER EDIT THIS CARD AT ALL? Answered by the SERVER (`serializers.task_card`), not
  // re-derived here. New in 2026-08-14: an employee's board now carries their whole DEPARTMENT, and
  // almost none of it is theirs to touch — so for the first time a visible card can be read-only for
  // an ordinary member. Drag, the inline ✕, the status control and the drawer's save all consult
  // this. Absent (undefined) means the payload named no viewer, which only happens on surfaces that
  // list somebody else's work; treating that as editable would be the optimistic guess this exists to
  // avoid, so it falls back to false for a card that carries the flag's siblings.
  // An Atrium card carries no `can_edit` — it has no Sentinel row to ask — and the server only ever
  // lists one to team_lead+ (`can_view_atrium`), so for anyone who is holding one, `can_edit_atrium`
  // is already satisfied by not being the read-only seat.
  const canEditCard = (t) => !readOnly
    && (t.source === "atrium" || t.can_edit === undefined || t.can_edit === true);

  // Board-only styles (styles.css stays untouched): the hover ✕ on cards. Injected once,
  // same pattern as the Coach FAB styles in app.js — CSP allows style elements, not inline JS.
  if (!document.getElementById("tb-style")) {
    const st = document.createElement("style");
    st.id = "tb-style";
    st.textContent = `
      /* 🔴 The task detail is a WIDE CENTRED MODAL, not a side panel.
         A split view was tried on 2026-08-03 and REMOVED the same day, because the board's own
         dimensions make it impossible: 5 columns x 288px + gaps = 1496px, plus a 248px sidebar and a
         ~340px panel = ~2150px before anything breathes. The board already scrolls horizontally at
         1800px, so the panel squeezed the columns AND cramped itself -- and at 340px wide the
         '.spread' field grid (minmax 220px) collapsed to ONE column, so eleven label/value pairs
         stacked up before you reached the work breakdown. In '.modal.wide' (920px) that same grid
         gives four columns. Don't re-add a docked panel without doing this arithmetic first.
         🔴 NO BACKTICKS ANYWHERE IN THIS COMMENT: it lives inside a template literal, so a
         markdown-style code span would CLOSE the string and the rest parses as a tagged template
         call ("...".spread is not a function). node --check does NOT catch it -- it is valid
         syntax, and it only blows up at mount() time. Quote selectors with ' instead.
         The body is two columns: the record on the left, the work + conversation on the right --
         which is also what makes the modal shorter than the panel ever was. */
      .tb-cols{display:grid;grid-template-columns:1.05fr .95fr;gap:26px;align-items:start}
      .tb-cols > *{min-width:0}
      /* One column on a narrow screen (or a phone), where 920px is not available anyway. */
      @media (max-width:820px){.tb-cols{grid-template-columns:1fr;gap:22px}}

      /* ======================================================================
         THE TASK RECORD (2026-08-06, ported from the same prototype).
         Reading order is the order the questions are asked: what is wrong with
         this -> who is on it -> the four facts -> the record and the work.

         Nothing is printed twice. Due date and Priority used to appear in the
         facts area AND two inches below in the field grid; a record that repeats
         itself reads as longer than it is, and the reader stops trusting either
         copy. The .kv list carries only what the facts strip does not. */
      .tb-detail .modal-head{border-bottom:0;padding-bottom:0}
      /* The modal title is now a KICKER -- 'Rooming House Expert - Task 110 - shared with the
         client'. The task's own name is an h2 at the top of the body, because it is the loudest
         thing in the dialog and a 16px head could not carry it. */
      .tb-detail .modal-head h3{font-size:10px;font-weight:800;letter-spacing:.9px;
        text-transform:uppercase;color:var(--muted)}
      .tb-detail .modal-body{padding-top:10px}
      .tb-h{font-size:19px;line-height:1.3;letter-spacing:-.4px;color:var(--ink);margin:0 0 16px}
      /* ONE notice, the worst true thing -- the same ladder the card's flag uses. A left edge
         rather than a filled box: five stacked coloured panels was the state this replaced. */
      .tb-note{border-left:2px solid var(--line-strong);padding:2px 0 2px 13px;margin:0 0 18px;
        font-size:12.5px;color:var(--text)}
      .tb-note.bad{border-left-color:var(--danger)}
      .tb-note.warn{border-left-color:var(--warn)}
      .tb-note b{color:var(--ink);font-weight:700}
      .tb-note .say{margin-top:5px;color:var(--sub);white-space:pre-wrap}
      .tb-note .meta{margin-top:4px;font-size:11px;color:var(--muted)}
      .tb-note .act{margin-top:7px}
      /* WHO IS ON THIS, above the facts: it is the question the board could not answer and the
         first thing anyone opening a card looks for. */
      .tb-crew{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:2px 0 16px}
      .tb-crew .lead{display:flex;align-items:center;gap:10px}
      .tb-crew .lead .nm{font-size:14px;font-weight:700;color:var(--ink);line-height:1.25}
      .tb-crew .lead .rl{font-size:11px;color:var(--muted)}
      .tb-crew .bar{width:1px;height:28px;background:var(--line)}
      .tb-crew .sup{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
      .tb-crew .sup-p{display:flex;align-items:center;gap:7px}
      .tb-crew .sup-p .nm{font-size:12.5px;color:var(--text);font-weight:600;line-height:1.2}
      .tb-crew .sup-p .st{font-size:10.5px;color:var(--muted)}
      .tb-crew .none{font-size:12.5px;color:var(--muted)}
      .tb-facts{display:flex;flex-wrap:wrap;gap:0 26px;padding:14px 0;
        border-top:1px solid var(--line-soft);border-bottom:1px solid var(--line-soft)}
      .tb-facts .k{font-size:9.5px;font-weight:800;letter-spacing:.7px;text-transform:uppercase;color:var(--muted)}
      .tb-facts .v{font-size:13px;color:var(--ink);font-weight:600;margin-top:3px;
        display:flex;align-items:center;gap:6px}
      .tb-facts .v.bad{color:var(--danger)}
      .tb-facts .v.warn{color:var(--warn)}
      .tb-facts select{width:auto;min-width:110px;height:28px;font-size:12.5px;padding:0 6px}
      .tb-kv{display:grid;grid-template-columns:auto 1fr;gap:9px 18px;font-size:12.5px;
        align-items:baseline;margin:0}
      .tb-kv dt{color:var(--muted)}
      .tb-kv dd{margin:0;color:var(--text)}
      /* TABS over the work / conversation column. All three panes stay in the DOM and are toggled
         with [hidden] -- they are wired ONCE when the modal opens (the breakdown alone has eight
         handlers per row), and re-rendering a pane on every tab click would drop that wiring. */
      .tb-tabs{display:flex;gap:18px;border-bottom:1px solid var(--line-soft);margin-bottom:14px}
      .tb-tabs button{border:0;background:transparent;padding:0 0 9px;font-size:12.5px;font-weight:700;
        color:var(--muted);border-bottom:2px solid transparent;margin-bottom:-1px;cursor:pointer}
      .tb-tabs button:hover{color:var(--text)}
      .tb-tabs button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--ink)}
      .tb-tabs .n{color:var(--muted);font-weight:500;margin-left:4px}
      .tb-move{display:inline-flex;align-items:center;gap:7px;
        border:1px solid var(--line);border-radius:var(--r-ctl);padding:3px 5px 3px 11px}
      .tb-move span{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--muted)}
      .tb-move select{width:auto;border:0;background:transparent;height:26px;
        font-size:12.5px;font-weight:700;color:var(--ink);padding:0 2px}
      /* 🔴 THE FOOTER IS ONE ROW, and staying one row is a constraint, not a preference. A record
         has up to a dozen possible actions; at most three of them are ever what you opened the card
         for. Wrapped onto two rows it reads as broken (reported 2026-08-06) and the primary action
         ends up stranded under a red Delete. So: the column control, Edit, the two or three actions
         this STATE actually offers, then everything rare behind "More", then the two ways out.
         'flex-wrap:wrap' stays as the safety net for a narrow window; it is not the design.
         (NO BACKTICKS IN THIS COMMENT — it lives inside a template literal; see the note at the
         top of this style block.) */
      .tb-detail .modal-foot{flex-wrap:wrap;justify-content:flex-start;align-items:center;row-gap:8px}
      .tb-detail .modal-foot .tb-end{margin-left:auto;display:inline-flex;gap:10px;align-items:center}
      /* <details> rather than a JS popover: keyboard- and screen-reader-operable for free, no popup
         layer, no document-level click handler to leak. Same pattern as the task form's
         '.tk-extra'. It opens UPWARDS because it lives in a footer. */
      .tb-more{position:relative}
      .tb-more > summary{list-style:none;cursor:pointer;display:inline-flex;align-items:center;gap:6px;
        border:1px solid var(--line);background:var(--white);color:var(--ink);border-radius:var(--pill);
        padding:9px 16px;font-size:13.5px;font-weight:700;white-space:nowrap;user-select:none}
      .tb-more > summary::-webkit-details-marker{display:none}
      .tb-more > summary::after{content:"⌄";font-size:13px;line-height:1;margin-top:-4px;color:var(--muted)}
      .tb-more > summary:hover{border-color:var(--line-strong)}
      .tb-more[open] > summary{border-color:var(--line-strong);background:var(--hover)}
      .tb-menu{position:absolute;bottom:calc(100% + 7px);left:0;z-index:5;min-width:238px;
        display:flex;flex-direction:column;gap:2px;padding:6px;border:1px solid var(--line);
        border-radius:13px;background:var(--card);box-shadow:var(--shadow-lg)}
      .tb-menu .btn{width:100%;justify-content:flex-start;border-color:transparent;background:transparent;
        border-radius:9px;padding:9px 11px;font-size:13px;font-weight:600;white-space:normal;text-align:left}
      .tb-menu .btn:hover{background:var(--hover);border-color:transparent}
      .tb-menu .btn:disabled:hover{background:transparent}
      .tb-menu .btn.danger{background:transparent;border-color:transparent;color:var(--danger)}
      .tb-menu .btn.danger:hover{background:var(--danger);color:#fff}
      .tb-menu hr{border:0;border-top:1px solid var(--line-soft);margin:4px 2px}

      /* ======================================================================
         THE QUIET CARD (2026-08-06, ported from frontend/taskboard_ux_prototype.html)

         THE ONE IDEA: a card says WHO is on it and WHETHER it is in trouble, and
         nothing else. Everything that is true of EVERY card -- the priority word,
         the filled label pill, the creator tag, the attachment count -- is noise,
         because a signal every card carries is not a signal. None of it is lost:
         the detail modal holds the whole record, one click away.

           * ONE flag per card, at most (see flagOf) -- the worst true thing wins
             and the rest stays silent.
           * The label is a 6px DOT, not a filled pill. It was the loudest thing on
             a board where it never varies within a client.
           * Colour means a problem. Green is progress and the lead's ring.
           * Faces: the LEAD is ringed, support sits beside them. Support has been
             on the model since 2026-08-06 and the card only printed the lead.
           * Overdue is carried by the DATE, in red, at the other end of the card --
             which is why it is deliberately NOT in the flag ladder. Spending the
             flag slot on it hid the actionable problem on the one card that had
             both ("late" beat "the client asked for changes").

         Rejected before, do not re-propose: left priority accent bars (2026-07-14),
         per-column money totals (2026-07-14), a docked side panel (2026-08-03). */
      /* 🔴 'flex:none' IS LOAD-BEARING. '.col-list' is a flex COLUMN, so its cards are flex items
         with the default 'flex-shrink:1' -- once a column holds more than fits, the browser squashes
         every card instead of scrolling, and the card clips its own title and loses its whole
         footer (faces, date, comment count). It was survivable while the card had no 'overflow'
         (the text simply spilled over the card below); the moment the progress hairline required
         'overflow:hidden', squashing became silent truncation. Never remove this to "let cards
         fit" -- the column scrolls, cards do not shrink.
         (No backticks in this comment: template literal.) */
      .col-list > .tcard{flex:0 0 auto}
      .tcard{position:relative;overflow:hidden;padding:11px 12px 13px;cursor:grab;
        box-shadow:none;transition:border-color .12s ease,box-shadow .12s ease}
      .tcard:hover{border-color:var(--line-strong);box-shadow:var(--shadow)}
      /* A parked card is deliberately not in play, so it must not read as loud as live work. */
      .tcard.quiet{background:transparent;border-style:dashed}
      .tcard.quiet .t-title{color:var(--sub);font-weight:550}
      .tcard .t-top{display:flex;align-items:center;gap:6px;margin-bottom:6px;min-height:16px}
      .tcard .t-disc{width:6px;height:6px;border-radius:50%;flex:none}
      .tcard .t-client{font-size:10px;font-weight:700;letter-spacing:.7px;text-transform:uppercase;
        color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
      /* The campaign is a SUB-grouping under the client, so it is one more segment of that same
         line rather than a chip. A pill was not tried and rejected here -- the label above it
         already lost that argument (see .t-disc): on a board where nearly every card in a column
         shares a value, a filled pill is the loudest thing on screen and says the least.
         Lowercase and lighter than the client, because the reading order is client -> campaign ->
         name. The '/' is generated content, so it disappears with the value instead of leaving a
         stranded separator. It shrinks BEFORE the client does: whose work this is outranks which
         campaign it belongs to when there is not room for both. */
      .tcard .t-camp{font-size:10px;font-weight:600;letter-spacing:.2px;color:var(--muted);
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex-shrink:2;opacity:.9}
      .tcard .t-camp::before{content:"/";margin-right:5px;opacity:.55}
      /* Right-aligned, and the ONLY coloured word on a healthy board. */
      .tcard .t-flag{margin-left:auto;flex:none;font-size:10px;font-weight:800;letter-spacing:.5px;
        text-transform:uppercase;color:var(--muted);white-space:nowrap}
      .tcard .t-flag.bad{color:var(--danger)}
      .tcard .t-flag.warn{color:var(--warn)}
      .tcard .t-title{font-size:13.5px;font-weight:650;color:var(--ink);line-height:1.4;letter-spacing:-.1px}
      .tcard .t-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:11px}
      .tcard .t-people{display:flex;align-items:center;gap:8px;min-width:0}
      .tcard .t-unassigned{font-size:11.5px;color:var(--muted);font-weight:550}
      .tcard .t-meta{display:flex;align-items:center;gap:9px;flex:none;margin-top:0;
        font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums}
      .tcard .t-meta .over{color:var(--danger);font-weight:700}
      .tcard .t-meta .soon{color:var(--warn);font-weight:600}
      .tcard .t-meta .ship{color:var(--green-strong)}
      .tcard .t-meta .cc{display:inline-flex;align-items:center;gap:3px}
      .tcard .t-meta .svg-ic{width:12px;height:12px}
      /* Progress is a 2px hairline on the card's own edge -- present when there is a breakdown,
         invisible when there is not. The old 'done/total' text said the same thing in a place the
         eye had to stop and read. */
      .tcard .t-bar{position:absolute;left:0;right:0;bottom:0;height:2px;background:var(--line-soft)}
      .tcard .t-bar > i{display:block;height:100%;background:var(--green);border-radius:0 2px 2px 0}

      /* FACES.
         🔴 An initials chip is NEUTRAL here, never a palette colour. The house avatar is a green
         gradient with a green glow, so a green chip sitting inside the green LEAD ring read as one
         solid blob and the ring stopped saying anything at all. Colour on this board means a
         problem, a person's photo, or progress -- never decoration. Photos are untouched, and the
         rest of the app (topbar, swimlane heads, people pages) keeps the green chip. */
      .tcard .avatar,.tb-crew .avatar,.tb-detail .avatar{box-shadow:none}
      .tcard .avatar:not(.has-photo),.tb-crew .avatar:not(.has-photo),
      .tb-detail .avatar:not(.has-photo){background:var(--muted);color:#fff}
      /* The lead is ringed green; anything of YOURS is ringed violet, which is what makes your own
         work findable on a board of sixty cards without reaching for a filter. Both rings at once
         is a card you lead. */
      .avatar.is-lead{box-shadow:0 0 0 1.5px var(--card),0 0 0 3px var(--green)}
      .avatar.is-me{box-shadow:0 0 0 1.5px var(--card),0 0 0 3px var(--violet)}
      .avatar.is-lead.is-me{box-shadow:0 0 0 1.5px var(--card),0 0 0 3px var(--green),0 0 0 4.5px var(--violet-bg)}
      .avatar.tb-xs{width:20px;height:20px;font-size:8px}
      .avatar.tb-md{width:26px;height:26px;font-size:10px}
      .avatar.tb-lg{width:40px;height:40px;font-size:14px}
      /* SUPPORT avatars on a card, overlapped. A 288px card cannot afford a row of them, and the
         negative margin is what keeps four people from pushing the date off the end. They spread
         on hover, so the count is still countable. */
      .tcard .t-support{display:inline-flex;align-items:center}
      .tcard .t-support .avatar{margin-left:-9px;box-shadow:0 0 0 1.5px var(--card);
        transition:margin-left .15s ease}
      .tcard .t-support .avatar.is-me{box-shadow:0 0 0 1.5px var(--card),0 0 0 3px var(--violet)}
      .tcard .t-support:hover .avatar{margin-left:-1px}
      .tcard .t-support-more{margin-left:-9px;height:26px;min-width:26px;padding:0 6px;
        display:inline-flex;align-items:center;justify-content:center;border-radius:var(--pill);
        background:var(--input);color:var(--sub);font-size:10.5px;font-weight:800;
        box-shadow:0 0 0 1.5px var(--card);transition:margin-left .15s ease}
      .tcard .t-support:hover .t-support-more{margin-left:-1px}
      /* The "supporting" marker on a By Employee lane, and in the drawer's Support field. */
      .pill.supporting{background:var(--input);color:var(--sub)}
      /* Its card-sized twin: in a supporter's lane the card has to say whose work it is, or the
         lane is indistinguishable from the July 2026 bug where a board listed other people's work. */
      .tcard .t-hat{flex:none;font-size:10px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;
        color:var(--sub);background:var(--input);border-radius:var(--pill);padding:1px 7px}

      /* An ORPHAN column: work stranded on a status Manage no longer lists (see columnsFor). Marked
         rather than styled loudly -- it is a temporary state somebody is meant to clear, not an
         error, and the cards inside it must still read as ordinary cards. */
      .col.col-orphan > .col-head .t{color:var(--warn)}

      /* 🔴 The ✕ and the bulk checkbox now sit IN the top row, in flow (2026-08-06). Both used to be
         absolutely positioned top-right, which is exactly where the quiet card puts its flag -- so
         "CLIENT ASKED" would have been sitting under the delete button on hover, on precisely the
         cards that need reading. Laid out in the row, nothing can overlap anything. */
      .tcard .t-del{flex:none;width:20px;height:20px;border:none;border-radius:6px;
        background:transparent;color:var(--muted);font-size:12px;line-height:1;cursor:pointer;
        display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity .12s ease,background .12s ease,color .12s ease}
      .tcard:hover .t-del,.tcard .t-del:focus-visible{opacity:1}
      .tcard .t-del:hover{background:var(--danger);color:#fff}
      @media (hover: none){.tcard .t-del{opacity:.55}}

      /* MOBILE MOVE CONTROL (WP 5.5, problem 2.2.6). Drag-and-drop was the board's ONLY move
         affordance, so on a phone the board is a horizontal scroll of cards that cannot be
         moved at all -- the drawer's status select was the only way, three taps away.
         A native select is deliberate: it hands phones the OS picker, it is keyboard and
         screen-reader operable for free, and it needs no popup layer.
         Hidden wherever a real pointer exists, because dragging is better there and a second
         control on every card is clutter. Still reachable by KEYBOARD on the desktop -- it
         appears on focus, which is the only move affordance a keyboard user has ever had. */
      .tcard .t-move{position:absolute;left:8px;right:34px;bottom:6px;width:auto;height:26px;
        font-size:11px;padding:0 6px;border-radius:7px;border:1px solid var(--line);
        background:var(--card);color:var(--muted);cursor:pointer;
        opacity:0;pointer-events:none}
      /* 🔴 '--fg' and '--accent' were used here and DEFINED NOWHERE (fixed 2026-08-17), so both
         declarations were invalid at computed-value time: the colour fell back to inherited and
         the border to 'currentColor'. The one move affordance a keyboard user has ever had
         revealed itself with no focus edge at all. Violet is the app's light-mode focus colour
         (styles.css gives every input 'border-color: var(--violet)' on focus).
         Single quotes throughout: a backtick in here would close this template literal. */
      .tcard .t-move:focus-visible{opacity:1;pointer-events:auto;color:var(--ink);border-color:var(--violet)}
      @media (hover: none){
        .tcard .t-move{position:static;display:block;width:100%;margin-top:8px;opacity:1;
          pointer-events:auto;height:32px;font-size:12px}
        /* Clear of the progress hairline, which is on the card's bottom edge. */
        .tcard{padding-bottom:14px}
      }

      /* BULK SELECTION (M7, WP 5.4). Opt-in: a permanent checkbox on every card is clutter on a
         board people mostly read, and it competes with drag for the same pointer. In flow at the
         head of the top row, for the same reason the ✕ is. */
      .tcard .t-pick{flex:none;width:14px;height:14px;margin:0;cursor:pointer}
      /* Violet, matching '.col.drag-over' (the board's other interaction outline) and the 'is-me'
         rings — never green, which is the LEAD ring on the same card. Was 'var(--accent)', an
         undefined token that fell back to 'currentColor': a picked card got a grey outline barely
         separable from its own 1px border, on the one feature whose whole job is to show you what
         you have selected. */
      .tcard.picked{outline:2px solid var(--violet);outline-offset:-2px}
      #tb-bulkbar{gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 12px;padding:10px 12px;
        border:1px solid var(--line);border-radius:10px;background:var(--card)}
      /* Load-bearing: the bar carries .row (display:flex), and an author display rule BEATS the UA
         [hidden]{display:none}. Without this the hidden attribute did nothing and the empty bar
         showed as a stray white strip under the filters on every load. Same trap as .ctxbar.
         (No backticks in this comment -- it lives inside a template literal.) */
      #tb-bulkbar[hidden]{display:none}
      /* 🔴 A HEIGHT ON A FORM CONTROL MUST RESET ITS PADDING. The base rule (styles.css) gives every
         select 'padding:10px 12px'; forcing 'height:30px' on top of that leaves a TEN-pixel content
         box, and a select clips its label to that box — so these three read as "Move to" with the
         bottom half sliced off. Nothing overflows and nothing errors, which is why it survived: the
         element is exactly the height it was told to be. Every other shrunken control in this file
         (the facts strip's priority, the record's Move to, the card's move select) already zeroes
         the vertical padding for the same reason. */
      #tb-bulkbar select{height:30px;padding:0 10px;font-size:12px;width:auto;min-width:130px}

      /* ======================================================================
         THE TOOLBAR (2026-08-06). Three stacked rows of chrome became two, and
         the second one answers questions people actually ask.

         What was there: a title row with FIVE buttons, then five filter controls
         plus an Overdue checkbox, a My work button and two saved-view controls,
         then a third row with Save view + Select. Fourteen controls above a board
         whose whole job is to be scanned — and the three that matter most on a
         Monday morning (what is late, what is waiting on me, what did the client
         ask for) were not among them, because they were not askable at all.

         The rule applied: a control earns its place by answering a question
         somebody actually asks. Everything else is a destination and belongs
         behind More -- reachable, not resident. Nothing was deleted. */
      .tb-head{display:flex;flex-wrap:wrap;gap:14px 20px;align-items:flex-start;
        justify-content:space-between;margin:28px 0 16px}
      .tb-head h3{font-size:20px;letter-spacing:-.4px;line-height:1.2}
      .tb-head .lead{margin-top:4px;font-size:12.5px;color:var(--muted);max-width:78ch;line-height:1.5}
      .tb-head-ctl{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
      /* The More menu is the footer's component reused; in a header it opens DOWNWARD and hangs
         off the right edge, because it is the last control on the line. */
      .tb-more.down .tb-menu{top:calc(100% + 7px);bottom:auto;left:auto;right:0}
      /* A quiet dot when something behind the menu wants attention (the client request queue). A
         menu that hides a queue with no outward sign is a queue nobody empties. */
      .tb-more .tb-dot{width:6px;height:6px;border-radius:50%;background:var(--violet-d);flex:none}
      .tb-menu .pill{margin-left:auto}

      .tb-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:16px}
      /* 🔴 An explicit basis, because the app's base rule is 'input{width:100%}' -- left to itself
         the search box eats the whole line and pushes every other control onto a second row, which
         is the layout this change exists to remove. (No backticks: template literal.) */
      .tb-bar input[type="search"]{flex:0 1 300px;width:300px;min-width:180px}
      .tb-bar select{width:auto;min-width:132px}
      .tb-sep{width:1px;height:22px;background:var(--line);margin:0 4px}
      /* ATTENTION PILLS. Each is a live COUNT of the cards in scope, and pressing one filters to
         them. They replace the Overdue checkbox, the My work button and the Priority select, and
         they add the two questions the board could not answer at all. A count is why they beat a
         select: "3 overdue" is information whether or not you press it, and a dropdown reading
         "All Priority" is not. */
      .tb-att{display:flex;gap:2px;flex-wrap:wrap}
      .att{border:0;background:transparent;padding:6px 10px;border-radius:9px;color:var(--muted);
        font:inherit;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap}
      .att b{font-weight:800;color:var(--text);font-variant-numeric:tabular-nums;margin-right:4px}
      .att:hover{background:var(--hover)}
      .att[aria-pressed="true"]{background:var(--input);color:var(--ink);
        box-shadow:inset 0 0 0 1px var(--line-strong)}
      .att.bad b{color:var(--danger)}
      .att.warn b{color:var(--warn)}
      /* Zero is still shown, dimmed: "0 overdue" is an answer, and a pill that vanishes takes the
         question with it. It just must not compete with a count that is not zero. */
      .att.zero{opacity:.45}
      .tb-shown{margin-left:auto;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;
        white-space:nowrap}

      /* THROUGHPUT (WP 6.2). A plain flex bar chart -- no charting library on this page, and one
         would be absurd for eight numbers. */
      .tp-chart{display:flex;align-items:flex-end;gap:8px;height:120px;padding:0 2px;
        border-bottom:1px solid var(--line)}
      .tp-col{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;
        height:100%;gap:4px}
      /* 🔴 These three lines used 'var(--accent)', which this app has never defined (fixed
         2026-08-17). An undefined custom property with no fallback makes the whole declaration
         invalid at computed-value time, so 'background' fell back to its initial 'transparent':
         the chart rendered eight correctly-sized INVISIBLE bars over their labels, with no error
         anywhere. Green because charts.js already draws its primary series in #54B948 (= --green)
         and throughput is the same kind of positive measure. */
      .tp-bar{width:100%;max-width:46px;border-radius:5px 5px 0 0;background:var(--green);
        min-height:2px}
      /* The partial week reads as provisional rather than as a cliff. */
      .tp-bar.tp-partial{background:repeating-linear-gradient(45deg,var(--green),var(--green) 4px,
        transparent 4px,transparent 8px);border:1px dashed var(--green);opacity:.75}
      .tp-n{font-size:11px;color:var(--muted)}
      .tp-clients{list-style:none;margin:0;padding:0;max-width:420px}
      .tp-clients li{display:flex;justify-content:space-between;gap:12px;padding:7px 0;
        border-bottom:1px solid var(--line-soft);font-size:13px}

      /* ======================================================================
         THE CREATE / EDIT FORM -- PROPERTY ROWS (2026-08-11).

         It was a two-column grid of boxed fields with EVERY routing field --
         client, department, lead, support, priority, service type, campaign --
         behind a collapsed 'More options'. Filing needed a name and nothing
         else, which was the point; the cost was that the eleven fields
         deciding where a card GOES were both one click away and, being
         collapsed, unread. Work arrived unrouted because the form never asked.

         So: the name and description LEAD as plain text (no box -- the modal
         title already says this is a task, and a bordered field around the
         loudest thing in the dialog only competes with it), and every other
         field is one labelled ROW. Nothing routing-related is hidden any more;
         only the genuinely rare fields still collapse.

         Controls sit FLUSH -- transparent ground, transparent border -- until
         hovered or focused. Nine boxed selects in a column read as a wall of
         chrome, and the row's own label already says what the control is.
         Written as ':not(:focus)' rather than a focus override on purpose: the
         app's own focus ring (violet in light, green in dark, styles.css)
         stays the one that paints, so this form cannot drift from every other
         input in the product.

         🔴 '.tf-row[hidden]' IS LOAD-BEARING. The UA's own '[hidden]' rule is
         beaten by ANY author 'display' declaration regardless of specificity,
         so '.tf-row{display:grid}' alone would leave a hidden row on screen --
         which is exactly how the share row rendered 'Client sees it' on a card
         with no client. Same trap the collapsed hold form hit in July.
         (NO BACKTICKS IN THIS COMMENT -- it lives inside a template literal;
         see the note at the top of this block.) */
      /* THE HEAD gets a kicker above the title -- 'TASK BOARD' over 'New task'. A lone 16px 'New
         task' on a 920px dialog is a lot of white space carrying one line, and the kicker is the
         same device the RECORD's head already uses (.tb-detail turns its h3 into one), so the two
         dialogs on this board now open the same way. It is a real element inside the h3 rather than
         a CSS 'content' string: the heading a screen reader announces should be the heading that is
         on screen, and generated content is announced inconsistently. */
      .tf-modal .modal-head h3{display:flex;flex-direction:column;gap:2px;
        font-size:17px;letter-spacing:-.25px}
      .tf-kicker{font-size:10.5px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;
        color:var(--muted)}
      .tf-name{width:100%;background:transparent;border:0;padding:0;font-size:21px;font-weight:700;
        color:var(--ink);letter-spacing:-.3px;line-height:1.3}
      .tf-name::placeholder{color:var(--line-strong)}
      .tf-name:focus{outline:none;box-shadow:none;background:transparent}
      .tf-desc{width:100%;background:transparent;border:0;padding:0;margin-top:9px;min-height:46px;
        font-size:13.5px;line-height:1.55;color:var(--text);resize:vertical}
      .tf-desc:focus{outline:none;box-shadow:none;background:transparent}
      .tf-desc::placeholder{color:var(--muted)}
      /* The naming rule as LIVE FEEDBACK rather than only a paragraph: each part of
         'Campaign | Action | Detail' fills in as you type its pipe. Still a HINT, never a
         validator -- a blank name saves as 'Untitled task' exactly as before, because §3 of the
         placement guidelines is about workers logging unplanned work the moment it appears. */
      .tf-pat{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:9px;
        font-size:11.5px;color:var(--muted)}
      .tf-pat .seg{padding:2px 9px;border-radius:var(--pill);background:var(--sunken);
        border:1px solid var(--line);font-weight:600;
        transition:background .15s,border-color .15s,color .15s}
      .tf-pat .seg.on{background:var(--green-bg);border-color:var(--green-line);color:var(--green-strong)}
      .tf-pat .sep{color:var(--line-strong);font-weight:700}
      .tf-pat .why{flex:1 1 100%;line-height:1.5;margin-top:2px}
      .tf-pat .why b{color:var(--sub);font-weight:700}
      .tf-rows{margin-top:18px;border-top:1px solid var(--line)}
      .tf-row{display:grid;grid-template-columns:152px 1fr;align-items:center;gap:12px;
        padding:7px 0;border-bottom:1px solid var(--line-soft)}
      .tf-row[hidden]{display:none}
      .tf-row>.k{display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600;color:var(--sub)}
      .tf-row>.k .svg-ic{width:14px;height:14px;color:var(--muted)}
      .tf-row>.v{min-width:0}
      .tf-row>.v input,.tf-row>.v select{font-size:13px;padding:6px 8px}
      .tf-row>.v input:not(:focus),.tf-row>.v select:not([multiple]):not(:focus){
        background:transparent;border-color:transparent}
      .tf-row>.v input:hover:not(:focus),.tf-row>.v select:hover:not(:focus){
        background:var(--input);border-color:var(--line)}
      /* A multi-select stays boxed at rest: it is a LIST, not a value, so there is nothing for a
         flush single line to show and the rows either side would run into it. */
      .tf-row>.v select[multiple]{padding:5px 7px;font-size:12.5px}
      /* ---- People picker (Support) ----
         Replaces the native 'multiple' select, whose ctrl-click selection model meant a plain click
         on a second name silently DESELECTED the first -- so staffing two people usually staffed
         one. The select is still there, hidden, carrying the value; this is only its face.
         NO BACKTICKS ANYWHERE IN THIS COMMENT -- see the top of this style block. */
      .ppick{border:1px solid var(--line);border-radius:var(--r-ctl);background:var(--input);
        overflow:hidden}
      .ppick-chips{display:flex;flex-wrap:wrap;gap:5px;padding:7px 8px;min-height:34px;
        align-items:center;border-bottom:1px solid var(--line)}
      .ppick-chip{display:inline-flex;align-items:center;gap:6px;padding:2px 4px 2px 2px;
        border-radius:999px;background:var(--card);border:1px solid var(--line);
        font-size:12px;font-weight:600;color:var(--ink)}
      /* The LEAD is shown here too, and marked -- "who is on this card" is unanswerable without
         them. It carries no remove button on purpose: the Lead row one field up owns that. */
      .ppick-chip.is-lead{border-color:var(--green);background:var(--green-soft);
        color:var(--green-strong)}
      .ppick-chip em{font-style:normal;font-size:9.5px;font-weight:800;letter-spacing:.08em;
        text-transform:uppercase;opacity:.75;padding-right:4px}
      .ppick-x{border:none;background:none;cursor:pointer;color:var(--muted);font-size:11px;
        line-height:1;padding:2px 3px;border-radius:50%}
      .ppick-x:hover{background:var(--sunken);color:var(--danger)}
      .ppick-none{font-size:12px;color:var(--muted);padding:2px 4px}
      .ppick-q{width:100%;border:none !important;border-bottom:1px solid var(--line) !important;
        border-radius:0 !important;background:var(--card) !important;font-size:12.5px}
      .ppick-q[hidden]{display:none}
      .ppick-list{max-height:168px;overflow-y:auto;background:var(--card)}
      .ppick-row{display:flex;align-items:center;gap:8px;padding:6px 9px;cursor:pointer;
        font-size:13px;color:var(--ink)}
      .ppick-row:hover{background:var(--hover)}
      .ppick-row input{width:15px;height:15px;flex:none;margin:0;accent-color:var(--green)}
      .ppick-row .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .ppick-row.locked{cursor:not-allowed;opacity:.7}
      .ppick-you{font-style:normal;font-size:9.5px;font-weight:800;letter-spacing:.08em;
        text-transform:uppercase;color:var(--violet-d);flex:none}
      /* A row whose control carries a sentence under it (the locked Lead picker, Support, Raised as)
         must sit its label with the FIRST line, not halfway down the block. */
      .tf-row.tall{align-items:start;padding:11px 0}
      .tf-row.tall>.k{padding-top:7px}
      .tf-row .rh{font-size:11.5px;color:var(--muted);line-height:1.5;margin-top:5px}
      .tf-row .rh[hidden]{display:none}
      /* Start and Due share one row -- they are one question, and two date inputs are narrow enough
         to sit side by side. Each caption is a real label wrapping its own input. */
      .tf-dates{display:grid;grid-template-columns:1fr 1fr;gap:10px}
      .tf-mini{display:flex;align-items:center;gap:8px;min-width:0}
      .tf-mini>span{font-size:11.5px;color:var(--muted);flex:0 0 auto}
      .tf-check{display:flex;align-items:center;gap:9px;font-size:12.5px;color:var(--text);cursor:pointer}
      .tf-check input{width:auto;flex:0 0 auto}
      /* WHAT THE CLIENT WILL READ gets its own sunken block instead of a tenth identical row: it is
         the entire content of the client's card, and the only field in this form they ever see. */
      .tf-cs{margin-top:18px;background:var(--sunken);border:1px solid var(--line);
        border-radius:var(--radius-sm);padding:13px 14px}
      .tf-cs .lb{font-size:12px;font-weight:700;color:var(--violet-d);display:flex;align-items:center;
        gap:7px;margin-bottom:8px}
      .tf-cs .lb .svg-ic{width:13px;height:13px}
      .tf-cs .lb i{font-weight:400;font-style:normal;color:var(--muted);font-size:11.5px}
      .tf-cs textarea{min-height:58px;font-size:13px}
      /* The keyboard shortcut sits at the far LEFT of the footer, pushing Cancel/Save right -- the
         footer is 'justify-content:flex-end', so the auto margin is what holds that split. */
      .tf-kbd{margin-right:auto;font-size:11.5px;color:var(--muted);white-space:nowrap}
      .tf-kbd kbd{font:inherit;font-size:11px;font-weight:700;color:var(--sub);background:var(--input);
        border:1px solid var(--line-strong);border-radius:4px;padding:0 5px}
      @media (max-width:560px){.tf-kbd{display:none}}
      .tf-more{margin-top:18px}
      .tf-more .two{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px}
      .tf-more .two > .field{margin-bottom:0}
      /* One column once the label gutter stops earning its width -- below this the value has ~120px,
         which turns every select into an ellipsis. */
      @media (max-width:680px){
        .tf-row,.tf-row.tall{grid-template-columns:1fr;gap:5px;align-items:start;padding:9px 0}
        .tf-row.tall>.k{padding-top:0}
        .tf-more .two{grid-template-columns:1fr}
      }`;
    document.head.appendChild(st);
  }

  // 🔴 SNAPSHOT FIRST, FETCH ONLY AS A FALLBACK. `S.vocab` is what boot() already fetched moments ago
  // (see the VOCAB note in app.js — one `/api/vocab` is seven SELECTs, and this page used to make it
  // the eighth through fourteenth). The board mounts immediately after boot, so the snapshot is
  // milliseconds old.
  //
  // But unlike the other consumers, this board CANNOT RENDER without `task_statuses` — they are its
  // columns. So a missing snapshot (boot's parallel vocab request failed) falls back to a real fetch
  // rather than dereferencing null and dying with a TypeError behind the generic "Couldn't load the
  // task board" toast. Reading a snapshot must never be the reason a page has no columns.
  const [vocab, clients, teams, people, templates] = await Promise.all([
    S.vocab ? Promise.resolve(S.vocab) : S.api("/api/vocab"),
    S.api("/api/clients"), S.api("/api/teams"), S.api("/api/people"),
    S.api("/api/tasks/templates"),
  ]);
  const STATUSES = vocab.task_statuses;
  // Every status carries the client stage it projects onto (task_status_meta, decision D13), which
  // is how the UI asks "is this a DONE column?" without ever naming "Completed" — that label is
  // renameable in Manage and nothing may key off it (AGENTS.md §5).
  const STAGE_OF = Object.fromEntries((vocab.task_status_meta || []).map((s) => [s.name, s.stage]));
  const isDoneStatus = (st) => STAGE_OF[st] === "completed";
  const peopleById = Object.fromEntries(people.map((p) => [p.id, p]));
  const teamsById = Object.fromEntries(teams.map((t) => [t.id, t]));
  // Service templates that match a chosen department (team), by team name.
  const templatesForTeam = (teamId) => {
    const name = teamsById[teamId] ? teamsById[teamId].name : null;
    return name ? templates.filter((t) => t.dept === name) : [];
  };
  // `priority` stays in this object for saved views written before 2026-08-06, which may carry one.
  // Nothing sets it any more: the Priority select became the `urgent` attention pill (see ATT).
  let filters = { client_id: "", team_id: "", priority: "", assignee_id: "" };
  let search = "";
  // 🔴 CAMPAIGN IS CLIENT-SIDE, and deliberately NOT a member of `filters` (2026-08-11). Everything
  // in that object is sent to the server by `load()`, and `campaign` is free TEXT with no vocabulary
  // behind it — its options are whatever the loaded cards happen to carry, so there is nothing for a
  // server filter to validate against and no reason to re-fetch the board to apply one. It behaves
  // like `search` and like the attention pills: counted and applied over the cards already fetched,
  // so toggling it can never change another control's number.
  let campaign = "";
  // 🔴 ONE derivation of "which campaign is this card part of", read by all four surfaces that ask
  // (the card, the search, the filter's option list and the drawer). It cannot simply be `t.campaign`:
  // every task created before 2026-08-04 has `campaign === title`, because one input used to write
  // both fields (docs/TASKBOARD_REBUILD.md §7), and those rows were deliberately never backfilled.
  // So a legacy card would print its own name twice — once as the campaign, once as the title — and
  // the filter would offer one bogus "campaign" per legacy task. Suppressed here rather than in each
  // reader, which is how two of them would drift.
  //
  // 🔴 THE COMPARISON IS NORMALISED; THE VALUE RETURNED IS NOT (2026-08-14). It was an EXACT string
  // compare, and a near miss defeats it completely — the live board carried the title "RHE Rooming
  // House Extension" against the campaign "RHE Rooming HouseExtension", ONE absent space, so that
  // card printed its own name on both lines. It was not merely ugly: `.t-client`/`.t-camp` are
  // `white-space: nowrap`, so the doubled line became the widest unbreakable thing in the column and
  // widened the COLUMN (see the 🔴 on `.col` in styles.css — a flex item's automatic minimum beats
  // its basis). One stray keystroke in a campaign name reshaped the board.
  //
  // Whitespace is stripped ENTIRELY, not collapsed: the difference here is a space that is missing,
  // so `\s+ -> " "` would not have matched it. Case is folded with it.
  // 🔴 And that is the whole normalisation, deliberately. Anything fuzzier (edit distance,
  // prefixes) starts suppressing campaigns that legitimately resemble their card's title, and a
  // grouping key you cannot see is a filter you cannot trust — strictly worse than the duplicate
  // it would hide. Equal-modulo-spacing IS the same string a human typed twice; nothing beyond
  // that is safe to assume.
  //
  // Still a DISPLAY rule only: the API keeps reporting the duplicate honestly and nothing rewrites
  // a stored value, so this stays reversible and no data is lost.
  const squash = (s) => (s || "").replace(/\s+/g, "").toLowerCase();
  const campaignOf = (t) => {
    const c = (t.campaign || "").trim();
    return c && squash(c) !== squash(t.title) ? c : "";
  };

  // The task-placement guidelines' naming rule, stated where the name is actually typed — and shown
  // on BOTH task forms (a Sentinel row and an Atrium client card), because the rule is about the
  // board they share, not about which system stores the row.
  //
  // 🔴 A HINT, NEVER A VALIDATOR. The rule exists so a title reads at a glance; §3 of those same
  // guidelines is entirely about workers logging unplanned work the moment it appears, and a form
  // that rejects a title is a form that loses that work instead of recording it imperfectly. The
  // client name is left out because the card already prints it ABOVE the title (the .t-client span in
  // `card()`), which is also the one part of this rule the UI can enforce for free: there is nowhere
  // in this form to type a client name, only a picker.
  const NAME_HINT = "Campaign work: <b>Campaign | Action | Detail</b> — e.g. Stratos | Increase daily "
    + "budget. Anything else: <b>Subject | Action | Detail</b> — e.g. Monthly Performance Report. "
    + "Leave the client out: the card shows it above the title.";
  const NAME_PLACEHOLDER = "Stratos | Increase daily budget";

  // Planned ahead vs added during the day — §1 vs §3 of the task-placement guidelines, classified by
  // the server (`services/task_origin`). 🔴 An UNKNOWN origin has no entry, so every reader falls
  // through to "don't print it": the rows created before the column existed, and every Atrium card
  // (no Sentinel creator to judge), are genuinely unclassified, and labelling them "Planned" would
  // assert something nobody knows — the same mistake as rendering a missing on-time rate as 0%.
  const ORIGIN_LABEL = { planned: "Planned ahead", added: "Added during the day" };
  // 🔴 THE ATTENTION PILLS — one live count each, independently toggleable (2026-08-06).
  //
  // They replace the Overdue checkbox, the My work button and the "All Priority" select, and they
  // add the two questions this board could not answer at all: what has a client asked for, and what
  // is waiting on an approval. Three properties are load-bearing:
  //
  //   * INDEPENDENT, not one-of. A single-choice pill row would undo the 2026-08-06 fix that made
  //     My work COMPOSE with the other filters — "mine + overdue, on this client" is a real
  //     question and it was unaskable for months. They AND together.
  //   * CLIENT-SIDE, over the cards already fetched, so the counts are consistent with each other
  //     and toggling one never changes another's number. `list_tasks` returns everything the viewer
  //     may see (no cap), so this narrows nothing the server would have shown.
  //   * `mine` is the SERVER's flag (task_perms.is_assigned: the card's lead, a supporter, or any
  //     phase/step owner) — never `t.assigned_to_id === S.user.id`, which is the narrower rule that
  //     told delegates their plate was empty in July 2026.
  //
  // 🔴 `urgent` reads the priority the CARD carries, not a server filter. The old select sent
  // `?priority=`, which re-fetched the board; as a pill it has to be counted from the same set as
  // its neighbours or the five numbers would describe five different boards.
  const ATT = [
    { key: "overdue", label: "overdue", tone: "bad",
      test: (t) => !!t.due_date && t.due_date < PH_TODAY && !isDoneStatus(t.status) },
    { key: "changes", label: "client asked", tone: "bad", test: (t) => !!t.open_changes },
    { key: "review", label: "to approve", tone: "warn", test: (t) => t.review_state === "pending" },
    { key: "urgent", label: "urgent", tone: "", test: (t) => t.priority === "Urgent" },
    { key: "mine", label: "on you", tone: "", test: (t) => !!t.mine },
  ];
  let att = {};                     // key -> true while that pill is pressed

  // --- Departments: this viewer belongs to a SET of them ------------------------------------------
  // 🔴 `S.user.team_ids`, not `S.user.team_id` (2026-08-14, `models.UserTeam`). A person may take
  // part in several departments — a designer who also sits with Acquisition, a lead covering a
  // second team — and the server's `task_perms._dept` is a set test now. Every comparison in this
  // file that used to read `=== S.user.team_id` would otherwise be the client-side half of the bug
  // that made those people's board show one department while the server sent them two.
  //
  // The `team_id` fallback is for a cached `me` payload served from before this shipped: the field
  // is absent there, and an empty list would silently hide the department the person actually has.
  const myTeamIds = (S.user.team_ids && S.user.team_ids.length)
    ? S.user.team_ids.slice()
    : (S.user.team_id != null ? [S.user.team_id] : []);
  const inMyDepts = (teamId) => teamId != null && myTeamIds.includes(teamId);
  // AM+ and the read-only seat work across the whole estate, so no department is "theirs" or "other"
  // — grouping the pickers for them would be a distinction that means nothing at their level.
  const estateWide = canManage || readOnly;
  const myTeamNames = myTeamIds.map((id) => (teamsById[id] || {}).name).filter(Boolean);
  // 🔴 Three forms, because every one of these sentences is user-facing and a person in two
  // departments would otherwise be told about "your departments's queue". The plural is not a
  // rare case here — it is exactly the case this feature was built for, so it cannot be the one
  // that reads like a bug.
  const plural = myTeamIds.length > 1;
  const deptWord = plural ? "departments" : "department";
  const deptPoss = plural ? "departments'" : "department's";
  const deptIs = plural ? "are" : "is";

  // Which question this board is answering, for the roles that have more than one (see #scope-seg).
  // Stored per browser like the density switch — it is one person's working habit, not org config.
  const SCOPE_KEY = "sentinel.tb.scope";
  // 🔴 The TABS AND THE DEFAULT BOTH DIFFER BY ROLE, and each default reproduces that role's board
  // exactly as it was — an upgrade must never look like cards have gone missing:
  //
  //   employee  On me (default) | My department   — `mine` is the board they had before the
  //                                                 department read landed on 2026-08-14
  //   lead      Everything (default) | My department(s)
  //
  // 🔴 A lead gets NO "On me" tab, deliberately. The attention pills on this same bar already carry
  // **on you** (`ATT.mine`), and a tab that repeats a pill two controls to its right is the exact
  // duplication this bar was cut from fourteen controls to six to remove. The employee's `mine` is
  // not that duplicate: it is their DEFAULT scope, so it defines the board rather than filtering it.
  const SCOPE_TABS = canMonitor
    ? [{ k: "all", label: "Everything",
         title: `Everything you can see: your ${deptWord}, work assigned to you, cards you raised for another department, and unclaimed client work` },
       { k: "dept", label: myTeamIds.length > 1 ? "My departments" : "My department",
         title: `Only work routed to your ${deptWord}${myTeamNames.length ? " (" + myTeamNames.join(", ") + ")" : ""}` }]
    : [{ k: "mine", label: "On me",
         title: `Work assigned to you, plus anything in your ${deptPoss} queue that nobody has picked up yet` },
       { k: "dept", label: myTeamIds.length > 1 ? "My departments" : "My department",
         title: "Everything your department is carrying, including your colleagues' cards. You can open them; only their owner or a lead can change them" }];
  const SCOPES = SCOPE_TABS.map((t) => t.k);
  let taskScope = SCOPES[0];
  try {
    const saved = localStorage.getItem(SCOPE_KEY);
    if (SCOPES.includes(saved)) taskScope = saved;
  } catch (e) { /* private mode */ }
  /** The pre-2026-08-14 board, exactly: work that is ON you (`mine` — the server's `is_assigned`,
   *  never `assigned_to_id === me`), plus your department's UNCLAIMED queue, which was always shared
   *  because an unowned card is nobody's job yet (`task_perms._team_queue`). Keeping the queue inside
   *  the narrow scope matters: it is the one part of the department view that is genuinely an
   *  invitation to act rather than something to read. */
  const onMyPlate = (t) => !!t.mine || (t.assigned_to_id == null && inMyDepts(t.assigned_team_id));
  let selection = new Set();        // M7 — ids ticked for a bulk action
  let allTasks = [];          // last fetch, unfiltered by the text search
  // View: "board" (status Kanban) | "employee" (swimlanes per person) | "monitor" (manager rollup).
  const params0 = new URLSearchParams(location.search);
  let mode = params0.get("view") || "board";
  if ((mode === "monitor") && !canMonitor) mode = "board";
  if (!["board", "employee", "monitor"].includes(mode)) mode = "board";
  // Employees/interns see only the tasks ASSIGNED to them — including no Atrium client card, which
  // is assigned to nobody here (the server enforces both in task_perms.can_view /
  // can_view_atrium). So the multi-person views and the assignee filter are noise: plain board only.
  if (!canMonitor) mode = "board";

  // --- Which filters this role actually needs ----------------------------------------------------
  // 🔴 THE FILTER BAR IS ROLE-SHAPED (2026-08-14). It used to render one identical row of controls
  // for every viewer, which meant the two roles at the ends of the ladder both got a bar that did
  // not fit: an employee was offered a picker of every department in the company (all but one of
  // which empties their board), and a team lead was offered the same flat list with nothing marking
  // the departments they lead. Neither control was WRONG — the server has always scoped the answer
  // — they just could not be used to ask anything.
  //
  // Two rules held to below, because the tempting fix breaks both:
  //   * **group, never truncate.** Every one of these filters can legitimately reach outside the
  //     viewer's own department (a card they raised for another team, a person from another team
  //     holding their work). Removing those options removes real queries; labelling them removes
  //     only the confusion.
  //   * **a control that cannot change the answer is not rendered at all** — the same rule the
  //     saved-views picker, the Clear button and the campaign filter already follow here.
  const otherTeams = teams.filter((t) => !inMyDepts(t.id));
  // Shown when there is more than one department to choose BETWEEN. A single-department employee's
  // board is that department, so the picker could only ever empty it; a manager always gets it.
  const showTeamFilter = teams.length > 1 && (estateWide || canMonitor || myTeamIds.length > 1);
  const optionList = (rows) => rows.map((t) => `<option value="${t.id}">${S.esc(t.name)}</option>`).join("");
  function teamOptionsHtml() {
    const head = `<option value="">All departments</option>`;
    if (estateWide || !myTeamIds.length) return head + optionList(teams);
    const mine = teams.filter((t) => inMyDepts(t.id));
    return head
      + `<optgroup label="${myTeamIds.length > 1 ? "My departments" : "My department"}">${optionList(mine)}</optgroup>`
      + (otherTeams.length ? `<optgroup label="Other departments">${optionList(otherTeams)}</optgroup>` : "");
  }
  // A person is "in my departments" if ANY of theirs is one of mine — `team_ids` is a set on both
  // sides now (serializers.user_full). The `team_id` fallback keeps this working against a payload
  // cached from before that field shipped.
  const sharesMyDept = (p) => (p.team_ids && p.team_ids.length
    ? p.team_ids.some(inMyDepts) : inMyDepts(p.team_id));
  function assigneeOptionsHtml() {
    const opt = (p) => `<option value="${p.id}">${S.esc(p.name)}</option>`;
    if (estateWide || !myTeamIds.length) return people.map(opt).join("");
    const mine = people.filter(sharesMyDept);
    const rest = people.filter((p) => !sharesMyDept(p));
    if (!mine.length) return people.map(opt).join("");
    return `<optgroup label="${myTeamIds.length > 1 ? "My departments" : "My department"}">${mine.map(opt).join("")}</optgroup>`
      + (rest.length ? `<optgroup label="Elsewhere">${rest.map(opt).join("")}</optgroup>` : "");
  }
  // The scope switch needs a department to narrow TO, and something to narrow FROM.
  const showScopeSeg = !estateWide && myTeamIds.length > 0;

  // Section-style header (h3) so the board reads as a dashboard section, not a second page title.
  root.innerHTML = `<div class="tb-head">
      <div><h3>Task Board</h3><div class="lead" id="tb-lead"></div></div>
      <div class="tb-head-ctl">
        ${canMonitor ? `<div class="seg" id="view-seg" role="tablist">
          <button type="button" data-view="board" role="tab">Board</button>
          <button type="button" data-view="employee" role="tab">By Employee</button>
          <button type="button" data-view="monitor" role="tab">Monitor</button>
        </div>` : ""}
        ${/* The AI-FIRST door (owner decision, 2026-09-02): describe what was agreed, the AI
              proposes tasks + assignees, the human overrides and confirms. New Task stays the
              always-working fallback beside it. */""}
        ${canCreate && S.hasCap("ai.draft") && window.OpsUI ? `<button class="btn" id="plan-ai" title="Describe what was agreed — AI proposes the tasks, you approve">✦ Plan with AI</button>` : ""}
        ${canCreate ? `<button class="btn primary" id="new-task">${S.ICON.plus}New Task</button>` : ""}
        ${/* Everything that is a DESTINATION rather than a filter. Each of these was a permanent
              button in the header, and each is opened a few times a week at most. The dot on the
              summary is the exception that keeps the request queue visible. */""}
        <details class="tb-more down"><summary>More<span class="tb-dot" id="tb-more-dot" hidden></span></summary>
          <div class="tb-menu">
            ${canManage ? `<button class="btn ghost" id="tb-requests" title="What clients have asked for, awaiting triage">Requests<span id="tb-req-n" class="pill violet" hidden></span></button>` : ""}
            <button class="btn ghost" id="filed-by-me" title="Work you raised for another team, and where it went">Filed by me</button>
            <button class="btn ghost" id="past-work" title="Completed work that has been filed">Past work</button>
            ${/* 🔴 In the MENU, not the header. That toolbar was deliberately cut from fourteen
                  controls to six (a6dc4a9); a density switch is set once and then never touched,
                  which is exactly the profile of everything else behind More. */""}
            <button class="btn ghost" id="tb-density" title="Narrower columns, so more of the board fits on screen at once"></button>
            ${!readOnly ? `<hr><button class="btn ghost" id="tb-select-toggle" title="Pick several cards and change them together">Select several…</button>` : ""}
            <hr><button class="btn ghost" id="f-save-view">Save this view…</button>
            <button class="btn ghost" id="f-manage-views">Manage saved views…</button>
          </div>
        </details>
      </div></div>
    <div class="tb-bar">
      <input id="f-search" class="tb-search" type="search" placeholder="Search tasks, clients, people…" autocomplete="off">
      <select id="f-client"><option value="">All clients</option>${clients.map((c) => `<option value="${c.id}">${S.esc(c.name)}</option>`).join("")}</select>
      ${/* 🔴 DEPARTMENTS ARE GROUPED, NOT TRIMMED (2026-08-14). This was a flat list of every
            department in the company, rendered identically for a team lead who can see one of them
            and for an AM who can see all of them — so a lead's most-used filter was mostly options
            that answer with an empty board, and nothing on screen said which ones were theirs.

            Grouped rather than filtered down, because "show me the work I filed for Design" is a
            real question a lead can ask: `_created` keeps a card they raised for another department
            on their board (that is what "Filed by me" lists), and cutting the option would take a
            working query away to tidy up the list. So the answer is to SAY which are theirs, not to
            decide for them.

            Hidden entirely for a single-department employee: their whole board is that one
            department, so every option here either changes nothing or empties the board — and the
            scope switch beside it already asks the only useful version of the question. */""}
      ${showTeamFilter ? `<select id="f-team">${teamOptionsHtml()}</select>` : ""}
      ${/* 🔴 SCOPE — the board answers more than one question for everybody below AM, so it says
            which one it is showing (2026-08-14).

            For an EMPLOYEE the distinction was new that day: `task_perms.can_view` began showing an
            ordinary member their whole department, not just what is on their own plate.

            For a TEAM LEAD it was never new and never expressible — their board has always carried
            four different things at once (their departments' work, cards on them personally, work
            they raised for another department, and unowned client cards), with one flat list and no
            way to ask for a subset. "What is on ME today" was the question a lead could not put to
            their own board; they got it by reading past everyone else's cards. Hence three tabs
            rather than the employee's two: `all` is what a lead's board has always been, and it
            stays their default, so nothing they had disappears on upgrade.

            AM / admin / super / viewer get no switch: they hold the whole estate, so "my department"
            is not a meaningful narrowing of it, and `#f-team` + `#f-assignee` above already cut it
            the ways they actually cut it. The control exists where the question exists — this is
            the per-role filter shape, not one bar with everything on it for everyone.

            🔴 And only when the viewer HAS a department. `task_perms._dept` matches on membership,
            so for somebody whose profile has none, "My department" is a tab that reveals nothing —
            the same empty-control problem as the saved-views picker and the Clear button. */""}
      ${showScopeSeg ? `<div class="seg sm" id="scope-seg" role="tablist">${SCOPE_TABS.map((t) =>
        `<button type="button" data-scope="${t.k}" role="tab" title="${S.esc(t.title)}">${S.esc(t.label)}</button>`).join("")}</div>` : ""}
      ${/* Options are filled by refreshCampaignList from the cards actually on the board, and it
            stays hidden until there is one — the same rule as the saved-views picker below, for the
            same reason: a dropdown whose only entry is its own placeholder cannot do anything. */""}
      <select id="f-campaign" title="Campaign" hidden><option value="">All campaigns</option></select>
      ${/* Grouped for a team lead for the same reason as the department picker, and with the same
            refusal to shorten the list: a lead may name anybody on a card they can see
            (`task_perms._lead_may_act`), so somebody outside their department really can be holding
            their work — dropping those names would make a card unfilterable by the one field that
            answers "who has it". */""}
      ${canMonitor ? `<select id="f-assignee"><option value="">Anyone</option><option value="none">Unassigned</option>${assigneeOptionsHtml()}</select>` : ""}
      <span class="tb-sep"></span>
      <span class="tb-att" id="tb-att"></span>
      ${/* Only when there is something to clear — a permanently visible Clear on an unfiltered
            board is a control that does nothing, which is what half this row used to be. */""}
      <button type="button" class="btn sm ghost" id="f-clear" hidden>Clear</button>
      <span class="tb-shown" id="tb-shown"></span>
      ${/* The saved-views picker appears only once you HAVE one (refreshViewList). An empty
            dropdown reading "Saved views…" is the definition of an unusable control. */""}
      <select id="f-view" title="Saved views" hidden></select>
    </div>
    <div id="tb-bulkbar" class="row" hidden></div>
    <div id="board"></div>`;

  // 🔴 The non-manager sentence follows the SCOPE now (2026-08-14). It used to read "Your tasks — the
  // work assigned to you", which stopped being true the moment `can_view` gained its department
  // branch; a board that describes itself wrongly is how the "nothing on you right now" bug went
  // unnoticed for a month.
  const boardLead = () => {
    // A lead's sentence follows the scope too, for the same reason the employee's does: the switch
    // changes which cards are on screen, and a board that keeps describing the widest view while
    // showing a narrow one is how somebody concludes their work has gone missing.
    const depts = myTeamNames.length ? ` (${myTeamNames.join(", ")})` : "";
    if (canMonitor) {
      if (showScopeSeg && taskScope === "dept") return `Work routed to your ${deptWord}${depts} — your ${plural ? "teams'" : "team's"} plate, without the cards you hold elsewhere. Use the “on you” pill for your own.`;
      return "Drag cards across columns. Client cards from Atrium are editable here too — every edit writes straight back to Atrium.";
    }
    if (taskScope === "dept") return `Everything your ${deptWord} ${deptIs} carrying${depts}. Cards that aren't yours are read-only — open them to read, but only their owner or a lead can change them.`;
    return `Your tasks — the work assigned to you, plus anything in your ${deptPoss} queue nobody has picked up. Drag cards across columns to update status.`;
  };
  const LEADS = {
    board: "",   // replaced per render by boardLead() — it depends on the scope switch
    employee: "Every teammate's tasks, grouped by person. Drag a card between columns to change its status.",
    monitor: "Team workload at a glance: open work, what's overdue, and what shipped this week. Click a row to see that person's tasks.",
  };

  // --- Saved views (M8, WP 5.4) -----------------------------------------------------------------
  // Every manager re-applied the same four filters on every visit. Stored per browser, like the
  // board's other preferences — these are one person's working habits, not org configuration, so
  // they do not belong in the database.
  const VIEWS_KEY = "sentinel.tb.views";
  const readViews = () => {
    try { return JSON.parse(localStorage.getItem(VIEWS_KEY) || "{}"); } catch (e) { return {}; }
  };
  const writeViews = (v) => {
    try { localStorage.setItem(VIEWS_KEY, JSON.stringify(v)); } catch (e) { /* private mode */ }
  };
  const currentView = () => ({ filters: { ...filters }, search, campaign, att: { ...att }, mode });

  function applyView(v) {
    if (!v) return;
    filters = { client_id: "", team_id: "", priority: "", assignee_id: "", ...(v.filters || {}) };
    search = v.search || "";
    // A view saved before the campaign filter existed simply has no campaign — "" is the right
    // answer for it, so no compatibility branch is needed here (unlike `att` below).
    campaign = v.campaign || "";
    // 🔴 A view saved BEFORE the pills existed carries `overdueOnly`/`mineOnly` booleans instead of
    // `att`. These live in each person's localStorage, so dropping the old keys would quietly change
    // what somebody's saved view shows — read both, write the new one.
    att = v.att ? { ...v.att } : { overdue: !!v.overdueOnly, mine: !!v.mineOnly };
    if (v.mode && (v.mode !== "monitor" || canMonitor)) mode = v.mode;
    // Push the restored state back into the controls, or the board would filter by values the
    // filter bar is not showing — which reads as a bug, not a view. (The pills are re-rendered from
    // `att` on every render, so they need no line here. Nor does #f-campaign: refreshCampaignList
    // rebuilds its options from the loaded cards on every render and marks `campaign` selected.)
    S.qs("#f-client").value = filters.client_id;
    // Guarded like #f-assignee below: the department picker is not rendered for a viewer who has
    // no department to choose between (see `showTeamFilter`), and a saved view written before that
    // rule existed can still carry a `team_id`. The filter itself still applies — it is sent by
    // `load()` from `filters` — there is simply no control to push it back into.
    if (S.qs("#f-team")) S.qs("#f-team").value = filters.team_id;
    if (S.qs("#f-assignee")) S.qs("#f-assignee").value = filters.assignee_id;
    S.qs("#f-search").value = search;
    load();
  }

  S.qs("#f-search").oninput = (e) => { search = e.target.value.trim().toLowerCase(); render(); };
  S.qs("#f-client").onchange = (e) => { filters.client_id = e.target.value; load(); };
  if (S.qs("#f-team")) S.qs("#f-team").onchange = (e) => { filters.team_id = e.target.value; load(); };
  // `render`, not `load` — the campaign filter narrows the cards already fetched (see `campaign`).
  S.qs("#f-campaign").onchange = (e) => { campaign = e.target.value; render(); };
  if (S.qs("#f-assignee")) S.qs("#f-assignee").onchange = (e) => { filters.assignee_id = e.target.value; load(); };
  if (canCreate) S.qs("#new-task").onclick = () => taskForm(null);
  // The AI Assistant executes approved actions through app.js; this hook lets the board
  // reflect a created/moved/parked card at once (guarded there - other pages have no board).
  window.SentinelReloadBoard = () => load();
  const planBtn = S.qs("#plan-ai");
  if (planBtn) planBtn.onclick = () => window.OpsUI.openAiPlanner(S, { onDone: () => load() });
  S.qs("#past-work").onclick = () => showPastWork();
  S.qs("#filed-by-me").onclick = () => showFiledByMe();

  // --- Column density -----------------------------------------------------------------------------
  // A `.col` is `flex: 0 0 var(--col-w)` and `--col-w` is a clamp() (styles.css, "THE COLUMN WIDTH
  // IS A VARIABLE"), so the board already narrows itself as the viewport shrinks. This is the
  // manual override for the case the clamp cannot answer: five-plus columns on a 1280px viewport,
  // where the honest choice between "see everything" and "read comfortably" belongs to the person
  // reading it. Per browser, like the saved views — a working habit, not org configuration.
  const DENSITY_KEY = "sentinel.tb.density";
  let dense = false;
  try { dense = localStorage.getItem(DENSITY_KEY) === "compact"; } catch (e) { /* private mode */ }
  // Appended to the view's own class, never assigned over it: renderBoard/renderByEmployee set
  // `board.className` outright, and the Monitor is a table with no columns to compress.
  const densityCls = () => (dense ? " dense" : "");
  const densityBtn = S.qs("#tb-density");
  const syncDensityBtn = () => { densityBtn.textContent = dense ? "Comfortable columns" : "Compact columns"; };
  syncDensityBtn();
  densityBtn.onclick = () => {
    dense = !dense;
    try { localStorage.setItem(DENSITY_KEY, dense ? "compact" : "comfortable"); } catch (e) { /* private mode */ }
    syncDensityBtn();
    render();
  };

  S.qsa("#view-seg button").forEach((b) => b.onclick = () => setMode(b.dataset.view));
  S.qsa("#scope-seg button").forEach((b) => b.onclick = () => {
    taskScope = b.dataset.scope;
    try { localStorage.setItem(SCOPE_KEY, taskScope); } catch (e) { /* private mode */ }
    render();
  });

  // One control to undo all of it. It only exists while something IS filtered (renderAttention), so
  // it is never a button that does nothing — and it clears the pills and the selects together,
  // because "why is the board empty?" is nearly always two of them at once.
  S.qs("#f-clear").onclick = () => {
    filters = { client_id: "", team_id: "", priority: "", assignee_id: "" };
    search = "";
    campaign = "";
    att = {};
    S.qs("#f-search").value = "";
    S.qs("#f-client").value = "";
    if (S.qs("#f-team")) S.qs("#f-team").value = "";
    S.qs("#f-campaign").value = "";
    if (S.qs("#f-assignee")) S.qs("#f-assignee").value = "";
    load();
  };

  // Closing the More menu after picking something: a menu that stays open over the thing it just
  // opened is the one bug every hand-rolled dropdown ships with.
  S.qsa(".tb-more .tb-menu .btn").forEach((b) => b.addEventListener("click", () => {
    const d = b.closest("details"); if (d) d.open = false;
  }));

  // --- Saved views: pick / save / manage ---------------------------------------------------------
  // 🔴 NO `prompt()` (2026-08-06). Saving used a native prompt, and DELETING one made you TYPE the
  // name of the view you wanted gone — from a list rendered inside the prompt's own text. It is the
  // only place in the app that asks anybody to retype an identifier, native dialogs are styled by
  // the browser and not by us, and some embedded contexts suppress them entirely (leaving a control
  // that looks live and does nothing). Both go through S.modal, like Park and Request changes.
  const viewSel = S.qs("#f-view");
  // 🔴 HIDDEN UNTIL THERE IS ONE. A dropdown whose only entry is its own placeholder ("Saved
  // views…") is a control that cannot do anything — it was one of the fourteen in the old bar, and
  // for anyone who had never saved a view it was permanently inert. Saving now lives under More,
  // and this picker appears the moment it has something to pick.
  function refreshViewList() {
    const names = Object.keys(readViews()).sort((a, b) => a.localeCompare(b));
    viewSel.hidden = !names.length;
    viewSel.innerHTML = `<option value="">Saved views…</option>`
      + names.map((n) => `<option value="${S.esc(n)}">${S.esc(n)}</option>`).join("");
  }
  refreshViewList();
  viewSel.onchange = () => {
    const pick = viewSel.value;
    viewSel.value = "";
    if (pick) applyView(readViews()[pick]);
  };
  S.qs("#f-manage-views").onclick = () => manageViews();

  function manageViews() {
    const names = Object.keys(readViews()).sort((a, b) => a.localeCompare(b));
    const mv = S.modal({
      title: "Saved views",
      body: names.length
        ? `<div class="card">${names.map((n) => `<div class="row between" style="padding:10px 12px;border-bottom:1px solid var(--line-soft);gap:12px">
             <strong style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${S.esc(n)}</strong>
             <button class="btn sm danger" data-vdel="${S.esc(n)}">Delete</button></div>`).join("")}</div>`
        : `<div class="empty">No saved views yet.</div>`,
      footer: `<button class="btn primary" id="mv-close">Done</button>`,
    });
    S.qs("#mv-close").onclick = mv.close;
    S.qsa("[data-vdel]", mv.root).forEach((b) => b.onclick = () => {
      const all = readViews();
      delete all[b.dataset.vdel];
      writeViews(all);
      refreshViewList();
      S.toast("View deleted", "ok");
      mv.close();
      if (Object.keys(all).length) manageViews();   // stay in the list while there is more to prune
    });
  }

  S.qs("#f-save-view").onclick = () => {
    const existing = Object.keys(readViews()).sort((a, b) => a.localeCompare(b));
    const sv = S.modal({
      title: "Save this view",
      body: `<div class="stack" style="gap:12px">
        <div class="form-hint">Saves the filters, the search box and the current tab — on this browser only, because these are your working habits, not org configuration.</div>
        <label class="field"><span>Name</span><input id="sv-name" placeholder="e.g. Overdue · Acquisition"></label>
        ${existing.length ? `<div class="sub" style="font-size:12px">Reusing a name overwrites it: ${existing.map((n) => S.esc(n)).join(" · ")}</div>` : ""}
      </div>`,
      footer: `<button class="btn ghost" id="sv-cancel">Cancel</button><button class="btn primary" id="sv-ok">Save view</button>`,
    });
    S.qs("#sv-cancel").onclick = sv.close;
    const box = S.qs("#sv-name", sv.root);
    box.focus();
    const save = () => {
      const name = box.value.trim();
      if (!name) { S.toast("Give the view a name", "err"); return; }
      const all = readViews();
      all[name] = currentView();
      writeViews(all); refreshViewList(); sv.close();
      S.toast(`Saved "${name}"`, "ok");
    };
    S.qs("#sv-ok").onclick = save;
    box.onkeydown = (ev) => { if (ev.key === "Enter") save(); };
  };

  // --- M7 bulk actions ---------------------------------------------------------------------
  // Selection mode is OPT-IN: a permanent checkbox on every card is clutter on a board people
  // mostly read, and it competes with drag-and-drop for the same pointer.
  let selecting = false;
  const bulkBar = S.qs("#tb-bulkbar");
  const selectBtn = S.qs("#tb-select-toggle");

  function bulkOptions() {
    // Only offer what this actor can actually do, so the bar never promises a 403.
    const status = `<select id="bk-status"><option value="">Move to…</option>${STATUSES.map((s) => `<option>${S.esc(s)}</option>`).join("")}</select>`;
    const prio = canPrioritizeOnForm ? `<select id="bk-prio"><option value="">Priority…</option>${vocab.priorities.map((p) => `<option>${S.esc(p)}</option>`).join("")}</select>` : "";
    const who = canMonitor ? `<select id="bk-who"><option value="">Assign to…</option><option value="none">Unassigned</option>${people.map((p) => `<option value="${p.id}">${S.esc(p.name)}</option>`).join("")}</select>` : "";
    return status + prio + who;
  }

  function renderBulkBar() {
    if (!selecting) { bulkBar.hidden = true; bulkBar.innerHTML = ""; return; }
    bulkBar.hidden = false;
    bulkBar.innerHTML = `<span class="section-label" id="bk-count">${selection.size} selected</span>
      ${bulkOptions()}
      <button type="button" class="btn sm ghost" id="bk-all">Select all shown</button>
      <button type="button" class="btn sm ghost" id="bk-none">Clear</button>`;
    const run = async (op, value) => {
      if (!selection.size) { S.toast("Nothing selected", "err"); return; }
      try {
        const res = await S.api("/api/tasks/bulk", {
          method: "POST", body: { ids: [...selection], op, value },
        });
        // 🔴 Report the skips. Partial success is the contract, and silently moving 7 of 10 cards
        // while the board redraws is exactly how someone loses track of the other three.
        const { updated, skipped } = res;
        if (skipped.length) {
          const why = [...new Set(skipped.map((s) => s.reason))].join("; ");
          S.toast(`${updated.length} updated · ${skipped.length} skipped — ${why}`, updated.length ? "ok" : "err");
        } else {
          S.toast(`${updated.length} updated`, "ok");
        }
        selection.clear();
        load();
      } catch (err) { S.toast(err.detail || "Bulk update failed", "err"); }
    };
    const st = S.qs("#bk-status");
    st.onchange = () => { const v = st.value; st.value = ""; if (v) run("status", v); };
    const pr = S.qs("#bk-prio");
    if (pr) pr.onchange = () => { const v = pr.value; pr.value = ""; if (v) run("priority", v); };
    const wh = S.qs("#bk-who");
    if (wh) wh.onchange = () => {
      const v = wh.value; wh.value = "";
      if (v) run("assignee", v === "none" ? null : Number(v));
    };
    S.qs("#bk-all").onclick = () => {
      // "Shown" needs no visibility test: this board REBUILDS its columns from the filtered list
      // (renderBoard takes `tasks.filter(matches)`), so every .tcard in the DOM is by definition a
      // card the current filters kept. An earlier version gated on `offsetParent !== null`, which
      // is a layout question — it selected nothing wherever layout is not computed.
      // Atrium-owned cards live in another system and the endpoint refuses their composite ids,
      // so they stay out — offering them could only ever produce a skip.
      S.qsa(".tcard").forEach((c) => {
        if (!String(c.dataset.id).startsWith("atrium:")) selection.add(Number(c.dataset.id));
      });
      syncSelection();
    };
    S.qs("#bk-none").onclick = () => { selection.clear(); syncSelection(); };
  }

  function syncSelection() {
    S.qsa(".tcard").forEach((c) => {
      const box = c.querySelector(".t-pick");
      if (box) box.checked = selection.has(Number(c.dataset.id));
      c.classList.toggle("picked", selection.has(Number(c.dataset.id)));
    });
    const n = S.qs("#bk-count");
    if (n) n.textContent = `${selection.size} selected`;
  }

  function wirePickers() {
    S.qsa(".t-pick").forEach((box) => {
      box.onclick = (e) => e.stopPropagation();      // ticking must not open the card
      box.onchange = (e) => {
        e.stopPropagation();
        const id = Number(box.closest(".tcard").dataset.id);
        if (box.checked) selection.add(id); else selection.delete(id);
        syncSelection();
      };
    });
    syncSelection();
  }

  if (selectBtn) {
    selectBtn.onclick = () => {
      selecting = !selecting;
      selectBtn.classList.toggle("primary", selecting);
      selectBtn.textContent = selecting ? "Done" : "Select";
      if (!selecting) selection.clear();
      renderBulkBar();
      render();
    };
  }

  // --- The client intake queue (D3, WP 3.3) ------------------------------------------------
  // A client's ask is NOT a task. It waits here until a manager accepts it, at which point it
  // becomes ordinary work; declining is a first-class outcome and needs a reason, because "we
  // are not doing this, because…" is an answer the client is owed.
  async function refreshRequestCount() {
    const badge = S.qs("#tb-req-n");
    if (!badge) return;
    // 🔴 The queue moved behind More (2026-08-06), so the count needs a second, outward sign: a
    // dot on the menu itself. A waiting client request that is invisible until you happen to open
    // a menu is a request nobody answers — which is worse than the crowded header it came out of.
    const dot = S.qs("#tb-more-dot");
    try {
      const { pending } = await S.api("/api/tasks/requests?status=pending");
      badge.textContent = pending;
      badge.hidden = !pending;      // no badge at all when the queue is empty, not a "0"
      if (dot) dot.hidden = !pending;
    } catch (e) { badge.hidden = true; if (dot) dot.hidden = true; }
  }

  async function openRequests() {
    let data;
    try { data = await S.api("/api/tasks/requests?status=pending"); }
    catch (err) { S.toast(err.detail || "Couldn't load the requests", "err"); return; }
    const rows = data.requests || [];
    const body = rows.length ? rows.map((r) => `
      <div class="card pad" data-req="${r.id}" style="margin-bottom:10px">
        <div class="row between" style="align-items:flex-start;gap:10px">
          <div style="min-width:0">
            <div style="font-weight:600">${S.esc(r.title)}</div>
            <div class="sub" style="font-size:12px;margin-top:2px">
              ${S.esc(r.client_name || r.client_key)}${r.requester_name ? " · " + S.esc(r.requester_name) : ""} · ${S.timeAgo(r.created_at)}
            </div>
            ${r.details ? `<div class="sub" style="margin-top:6px">${S.esc(r.details)}</div>` : ""}
          </div>
          <div class="row" style="gap:6px;flex:none">
            <select data-rq-team="${r.id}" title="Which department takes this on">
              <option value="">Department…</option>
              ${teams.map((tm) => `<option value="${tm.id}">${S.esc(tm.name)}</option>`).join("")}
            </select>
            <button class="btn sm primary" data-rq-accept="${r.id}">Accept</button>
            <button class="btn sm ghost" data-rq-decline="${r.id}">Decline</button>
          </div>
        </div>
      </div>`).join("")
      : `<div class="empty card pad">Nothing waiting. Client asks filed from Atrium land here.</div>`;

    const m = S.modal({
      title: "Client requests",
      wide: true,
      body: `<div class="lead" style="margin-bottom:12px">Asks filed by clients from their Atrium workspace. Accepting one turns it into a task on this board; declining records why.</div>${body}`,
      footer: `<button class="btn ghost" id="rq-close">Close</button>`,
    });
    S.qs("#rq-close").onclick = m.close;

    const after = async (msg) => {
      S.toast(msg, "ok");
      m.close();
      await refreshRequestCount();
      load();
    };
    S.qsa("[data-rq-accept]").forEach((b) => b.onclick = async () => {
      const id = b.dataset.rqAccept;
      const teamSel = S.qs(`[data-rq-team="${id}"]`);
      b.disabled = true;
      try {
        await S.api(`/api/tasks/requests/${id}/accept`, {
          method: "POST",
          body: { assigned_team_id: teamSel && teamSel.value ? Number(teamSel.value) : null },
        });
        await after("Accepted — it is on the board now");
      } catch (err) { b.disabled = false; S.toast(err.detail || "Couldn't accept that", "err"); }
    });
    // Declining asks the same way Park and Request changes ask — `askReason`, not a native prompt.
    // This is prose a CLIENT is owed, so a single-line browser dialog was the wrong box for it in
    // more than one sense: it can't be styled, and it invites one terse line.
    S.qsa("[data-rq-decline]").forEach((b) => b.onclick = () => askReason({
      title: "Decline this request",
      hint: "The client sees this reason on their own board. \"We are not doing this, because…\" is an answer they are owed.",
      label: "Why are we not doing this?",
      confirm: "Decline it",
      require: true,
      onSubmit: async (reason) => {
        b.disabled = true;
        try {
          await S.api(`/api/tasks/requests/${b.dataset.rqDecline}/decline`,
                      { method: "POST", body: { reason } });
          await after("Declined, with the reason on record");
        } catch (err) { b.disabled = false; S.toast(err.detail || "Couldn't decline that", "err"); }
      },
    }));
  }

  if (S.qs("#tb-requests")) {
    S.qs("#tb-requests").onclick = openRequests;
    refreshRequestCount();
  }

  function setMode(next) {
    mode = next;
    const u = new URLSearchParams(location.search);
    if (next === "board") u.delete("view"); else u.set("view", next);
    history.replaceState(null, "", location.pathname + (u.toString() ? "?" + u : ""));
    render();
  }

  // Fetch (filters hit the server), then hand off to the active view's renderer.
  async function load() {
    const q = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => { if (v) q.set(k, v); });
    // "Unassigned" is a choice, not an id: it becomes its own flag so assignee_id stays an int
    // server-side (?unassigned=1 — see list_tasks).
    if (filters.assignee_id === "none") { q.delete("assignee_id"); q.set("unassigned", "1"); }
    allTasks = await S.api("/api/tasks?" + q);
    render();
  }

  /** Is this card owned by somebody in the page-wide scope?
   *
   *  An Atrium client card has no Sentinel assignee at all — it belongs to a client, not a person
   *  — so a "whose work is this" scope excludes it rather than showing it under everyone. That is
   *  the same reasoning that gave those cards their own predicate on the server
   *  (task_perms.can_view_atrium): a row with nobody to test can't pass an ownership filter, and
   *  letting it through by default is how the board once showed an intern seven other people's
   *  cards (AGENTS.md §5). */
  function inPeopleScope(t) {
    if (!scope.scoped) return true;
    return t.assigned_to_id != null && scope.set.has(t.assigned_to_id);
  }

  // The text search is applied client-side so typing never re-hits the server.
  //
  // The text search + the attention pills, split in two so the pills can be COUNTED over the set
  // they filter. `inScope` is everything except the pills; `matches` is that plus the pills.
  //
  // 🔴 An Atrium-owned card carries `mine` too, since 2026-08-06. It used to be omitted, with the
  // reasoning that its owners are roster emails rather than Sentinel users — true when that was
  // written, and obsolete the day `services/atrium_identity` started resolving an Atrium lead to a
  // real Sentinel person. From then on a client card you lead showed YOUR face on the board, sat in
  // YOUR By Employee lane and counted toward YOU on the Monitor, while one button insisted it wasn't
  // yours. `as_board_card` sets `mine` from the same resolved owner all three of those read.
  //
  // OVERDUE (M9, WP 5.4) is compared against PH_TODAY so it agrees with the server's Asia/Manila
  // business rule rather than the viewer's timezone, and a FINISHED task is never overdue — its due
  // date stopped mattering when it shipped.
  function inScope(t) {
    // The Overview's page-wide people scope is applied FIRST and separately: it answers "WHOSE
    // work", the search and the selects answer "WHICH work". Two different questions, so the
    // page-level scope is layered on top of this board's own filters rather than replacing them.
    if (!inPeopleScope(t)) return false;
    // The role-scoped board/department switch (#scope-seg). Only ever NARROWING — every card here
    // already passed the server's `can_view`, so this can hide but never reveal — and only for the
    // roles that have the control. `all` is the no-op scope: it is what the board shows when nothing
    // is narrowing it, which is why an AM (who has no switch) never reaches these branches.
    if (showScopeSeg) {
      if (taskScope === "mine" && !onMyPlate(t)) return false;
      // 🔴 `dept` tests the CARD's department against the viewer's set, and deliberately does NOT
      // fall back to `mine` for a card with no department. "What is my team carrying" is a question
      // about routed work; a card nobody routed anywhere is not part of the answer, and quietly
      // padding this view with it would make the two tabs overlap for no stated reason.
      if (taskScope === "dept" && !inMyDepts(t.assigned_team_id)) return false;
    }
    // Campaign before the search, because it is the coarser question ("which campaign") and a card
    // outside the picked one is off the board however its text reads.
    if (campaign && campaignOf(t) !== campaign) return false;
    if (!search) return true;
    // Searching a person's name finds the cards they SUPPORT too, not just the ones they lead —
    // otherwise typing a colleague's name silently under-reports what they are on, which is the same
    // class of half-answer the "My work" button used to give.
    // The campaign is searchable too (2026-08-11): per §4 of the task-placement guidelines, work
    // raised after a campaign launches is a separate one-line card, so typing "Stratos" has to find
    // every card in that campaign — not only the ones whose title happens to repeat its name.
    return [t.title, t.assignee && t.assignee.name, t.client_name, campaignOf(t)]
      .concat((t.support || []).map((p) => p.name))
      .concat(t.atrium_support_names || [])
      .some((s) => (s || "").toLowerCase().includes(search));
  }

  const matches = (t) => inScope(t) && ATT.every((a) => !att[a.key] || a.test(t));
  const filtering = () => !!(search || campaign || att.overdue || att.changes || att.review
    || att.urgent || att.mine || filters.client_id || filters.team_id || filters.assignee_id);

  // The campaign options, rebuilt on every render because campaigns are free TEXT and not a
  // vocabulary: they are whatever the loaded cards carry. Built over the FETCHED set, not the
  // filtered one, so picking a campaign never removes its own option from the list.
  // The campaigns the board can actually see, in one place: the filter's options below and the New
  // Task form's autocomplete both read it. 🔴 A free-text grouping key drifts without a list to pick
  // from — "Stratos" and "stratos " are two campaigns to every `===` in this file — so offering the
  // existing names is what keeps the field usable as a key at all.
  const campaignNames = (pool) => [...new Set(pool.map(campaignOf).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));

  function refreshCampaignList(pool) {
    const sel = S.qs("#f-campaign");
    if (!sel) return;
    const names = campaignNames(pool);
    // 🔴 A selection that is no longer on the board is DROPPED. Without this, changing the client
    // filter can leave a campaign selected that none of the new cards belong to — an empty board
    // with its cause hidden in a control that is showing a value the board no longer contains.
    if (campaign && names.indexOf(campaign) < 0) campaign = "";
    sel.hidden = !names.length;
    sel.innerHTML = `<option value="">All campaigns</option>`
      + names.map((n) => `<option value="${S.esc(n)}"${n === campaign ? " selected" : ""}>${S.esc(n)}</option>`).join("");
  }

  // The pills, their counts, and the "N of M" beside them. Counted over `inScope` — the cards the
  // selects and the search left on the board — so pressing one pill never moves another's number.
  //
  // The parameter is `pool`, NOT `scope`: `scope` is the module-level PEOPLE scope that inScope,
  // laneOrder and renderMonitor all read, and shadowing it with an array here is one edit away from
  // a filter silently counting the wrong thing.
  function renderAttention(pool, shown) {
    const bar = S.qs("#tb-att");
    if (bar) {
      bar.innerHTML = ATT.map((a) => {
        const n = pool.filter(a.test).length;
        // "to approve" is a job; "in review" is a status. Only a seat that can actually decide a
        // review gets the verb — offering the job to somebody who cannot do it is the same lie as
        // a button that can only answer 403.
        const label = (a.key === "review" && !canMonitor) ? "in review" : a.label;
        return `<button type="button" class="att ${a.tone}${n ? "" : " zero"}" data-att="${a.key}"
          aria-pressed="${!!att[a.key]}"><b>${n}</b>${label}</button>`;
      }).join("");
      S.qsa("#tb-att .att").forEach((b) => b.onclick = () => {
        att[b.dataset.att] = !att[b.dataset.att];
        render();
      });
    }
    const clear = S.qs("#f-clear");
    if (clear) clear.hidden = !filtering();
    const count = S.qs("#tb-shown");
    // Only while something is filtered: "34 of 34" on an untouched board is noise, and the whole
    // point of this row is that a control says nothing until it has something to say.
    if (count) count.textContent = filtering() ? `${shown} of ${allTasks.length}` : "";
  }

  /** Lane / row order. With a page scope active the board follows the Team-progress table's
   *  ordering (fastest first, or whatever it's sorted by) so both halves of the Overview read
   *  top-to-bottom the same way; otherwise it's alphabetical, as before. */
  function laneOrder(a, b) {
    if (scope.order.length) {
      const rank = (k) => { const i = scope.order.indexOf(Number(k)); return i < 0 ? Infinity : i; };
      const d = rank(a) - rank(b);
      if (d) return d;
    }
    return (peopleById[a]?.name || "").localeCompare(peopleById[b]?.name || "");
  }

  function render() {
    S.qs("#tb-lead").textContent = (mode === "board" ? boardLead() : LEADS[mode])
      + (scope.scoped
        ? ` · scoped to ${scope.ids.length} ${scope.ids.length === 1 ? "person" : "people"} from Team progress`
        : "");
    S.qsa("#view-seg button").forEach((b) => b.classList.toggle("on", b.dataset.view === mode));
    S.qsa("#scope-seg button").forEach((b) => b.classList.toggle("on", b.dataset.scope === taskScope));
    S.qs("#f-search").closest(".tb-bar").style.display = mode === "monitor" ? "none" : "";
    const board = S.qs("#board");
    board.className = mode === "board" ? "board" + densityCls() : "";
    // 🔴 STRICTLY BEFORE the filter below, because it can CLEAR a stale `campaign` (see its own
    // comment) and `inScope` reads that variable. Run it afterwards and the board would spend one
    // whole render filtered by a campaign the select had already stopped offering.
    refreshCampaignList(allTasks);
    // `pool`, not `scope`: the module-level `scope` is the page-wide PEOPLE scope, and this
    // function reads it three lines up for the lead text. A `const scope` here would put that
    // read in the temporal dead zone and throw before the board ever painted.
    const pool = allTasks.filter(inScope);
    const tasks = pool.filter((t) => ATT.every((a) => !att[a.key] || a.test(t)));
    renderAttention(pool, tasks.length);
    if (mode === "monitor") return renderMonitor(board);
    if (mode === "employee") return renderByEmployee(board, tasks);
    return renderBoard(board, tasks);
  }

  // 🔴 A status with no column USED TO SWALLOW ITS CARDS. `byStatus` grew a bucket for any status
  // the board didn't know, and then only `STATUSES` was rendered — so the cards in it vanished with
  // no error and no empty state (AGENTS.md §5, "Removing a board column is TWO moves"). That is the
  // documented failure mode of deleting a task_vocab row while work still holds it, and the board
  // was the surface that hid it. Any leftover status now gets its own column at the end, labelled,
  // so the work is visible and can be dragged somewhere real. Never silently.
  function columnsFor(tasks) {
    const extra = [];
    tasks.forEach((t) => {
      if (STATUSES.indexOf(t.status) < 0 && extra.indexOf(t.status) < 0) extra.push(t.status);
    });
    return STATUSES.concat(extra);
  }

  function renderBoard(board, tasks) {
    const cols = columnsFor(tasks);
    const byStatus = Object.fromEntries(cols.map((s) => [s, []]));
    tasks.forEach((t) => (byStatus[t.status] || (byStatus[t.status] = [])).push(t));
    board.className = "board" + densityCls();
    board.innerHTML = cols.map((st) => {
      // An orphan column is work stranded on a retired status. It renders so nobody loses it, but it
      // takes no NEW cards: `create_task` 400s a status that isn't in `task_config.statuses`, so an
      // Add card here could only ever fail. Drag the cards out and the column disappears by itself.
      const orphan = STATUSES.indexOf(st) < 0;
      return `
      <div class="col${orphan ? " col-orphan" : ""}" data-status="${S.esc(st)}">
        <div class="col-head"><span class="t">${S.esc(st)}</span><span class="c">${byStatus[st].length}</span></div>
        ${orphan ? `<div class="form-hint" style="margin:0 0 8px;border-left:3px solid var(--warn)">This column no longer exists in Manage → Task Fields. Move this work somewhere real and it will disappear.</div>` : ""}
        ${/* 🔴 (t) => card(t), never a bare `card`: .map passes the INDEX as the second argument,
              which card() reads as a By Employee lane id. An index that happened to equal a
              supporter's user id printed a "supporting" hat on a card in the ordinary board. */""}
        <div class="col-list" data-status="${S.esc(st)}">${byStatus[st].map((t) => card(t)).join("")}</div>
        ${(canCreate && !orphan) ? `<button class="col-add" data-status="${S.esc(st)}">${S.ICON.plus}<span>Add card</span></button>` : ""}
      </div>`;
    }).join("");
    wireDnD();
    wireAddButtons();
    wireCardClicks();
    wireMoveSelects();
    wirePickers();
  }

  // Swimlanes: one lane per person that has tasks, plus an Unassigned lane. Cards sit in mini
  // status columns inside the lane; drag stays WITHIN a lane (moving between people would be a
  // reassignment, which belongs in the detail drawer, not a drag).
  function renderByEmployee(board, tasks) {
    const byUser = new Map();
    const push = (key, t) => {
      if (!byUser.has(key)) byUser.set(key, []);
      byUser.get(key).push(t);
    };
    tasks.forEach((t) => {
      // 🔴 A SUPPORTED CARD APPEARS IN EVERY PARTICIPANT'S LANE (2026-08-06), the lead's and each
      // supporter's, marked so it is never mistaken for work they own. This groups by the same
      // several-people-per-card truth the Monitor already reports — before support existed the two
      // could not disagree, because a card had exactly one owner. Leaving supporters out would mean
      // a person's own lane omitted work that their Monitor row counts and their board shows.
      //
      // The consequence, stated out loud because it looks like a bug: **the lane counts add up to
      // more than the number of cards.** That is the same property `assigned_user_ids` documents and
      // the Monitor's legend already explains — shared work is counted on every plate it is on.
      // Do NOT "fix" it by picking one lane per card; that re-hides exactly what this surfaced.
      const support = t.support_ids || [];
      if (t.assigned_to_id == null && !support.length) return push("none", t);
      if (t.assigned_to_id != null) push(t.assigned_to_id, t);
      support.forEach((uid) => { if (uid !== t.assigned_to_id) push(uid, t); });
    });
    // Order: named people first (by the page scope's ranking, else alpha), Unassigned last.
    const keys = [...byUser.keys()].filter((k) => k !== "none").sort(laneOrder);
    if (byUser.has("none")) keys.push("none");

    if (!keys.length) { board.innerHTML = `<div class="empty">No tasks match.</div>`; return; }

    board.className = "swimlanes" + densityCls();
    // Same columns in every lane (they have to line up), derived from the WHOLE filtered set so an
    // orphan status doesn't swallow one person's cards the way it used to swallow the board's.
    const cols = columnsFor(tasks);
    board.innerHTML = keys.map((k) => {
      const person = k === "none" ? null : peopleById[k];
      const list = byUser.get(k);
      const byStatus = Object.fromEntries(cols.map((s) => [s, []]));
      list.forEach((t) => (byStatus[t.status] || (byStatus[t.status] = [])).push(t));
      const head = person
        ? `${S.avatar(person, "sm")}<div class="ln"><div class="n">${S.esc(person.name)}</div><div class="r">${S.esc(person.role_label || person.role || "")}</div></div>`
        : `<div class="avatar sm">–</div><div class="ln"><div class="n">Unassigned</div></div>`;
      return `<section class="lane" data-uid="${k}">
        <div class="lane-head">${head}<span class="lane-count">${list.length}</span></div>
        <div class="lane-board">${cols.map((st) => `
          <div class="col" data-status="${S.esc(st)}">
            <div class="col-head"><span class="t">${S.esc(st)}</span><span class="c">${byStatus[st].length}</span></div>
            <div class="col-list" data-status="${S.esc(st)}" data-uid="${k}">${byStatus[st].map((t) => card(t, k)).join("")}</div>
          </div>`).join("")}</div>
      </section>`;
    }).join("");
    wireDnD({ sameLane: true });
    wireCardClicks();
    wireMoveSelects({ sameLane: true });
    wirePickers();
  }

  // Trailing window for the DERIVED columns (cycle time, on-time rate). The column counts stay live.
  // 30 days is long enough that a quiet fortnight doesn't erase somebody's record and short enough
  // that it still describes how the team works now. Sent to the server rather than assumed, so the
  // legend under the table and the numbers in it can never disagree.
  const MONITOR_WINDOW_DAYS = 30;

  async function renderMonitor(board) {
    board.className = "monitor";
    board.innerHTML = `<div class="skeleton-row">Loading team…</div>`;
    let rows;
    try { rows = await S.api("/api/tasks/summary?days=" + MONITOR_WINDOW_DAYS); }
    catch (err) { board.innerHTML = `<div class="empty">${S.esc(err.detail || "Couldn't load the team summary.")}</div>`; return; }
    // Narrowed by the page-wide scope, but NOT re-ordered by it: Monitor exists to rank by
    // workload (heaviest and most overdue first), which is a different question from growth speed.
    if (scope.scoped) rows = rows.filter((r) => scope.set.has(r.user.id));
    if (!rows.length) {
      board.innerHTML = `<div class="empty">${scope.scoped
        ? "No teammates in the current Team-progress filter."
        : "No teammates to show."}</div>`;
      return;
    }
    // 🔴 Derived from the live vocabulary and coloured by STAGE, never by the status LABEL. This
    // was a hardcoded four-name list, which had two failure modes that look identical to the
    // reader — a silently missing segment. (1) Renaming a column in Manage (WP 1.2 renamed Blocked
    // to Parked) dropped its work off every workload bar, because `r.counts` is keyed by the
    // current label. (2) A status somebody ADDED was never counted at all, so a teammate with ten
    // cards in it read as idle. The bar shows OPEN work, so completed-stage columns are excluded
    // — everything else earns a segment whatever it is called.
    const SEG_CLS = { todo: "s-todo", in_progress: "s-prog", revision: "s-rev", blocked: "s-block" };
    const barSegs = STATUSES.filter((s) => STAGE_OF[s] !== "completed");
    const segCls = Object.fromEntries(barSegs.map((s) => [s, SEG_CLS[STAGE_OF[s]] || "s-todo"]));
    const staleDays = (rows[0] && rows[0].stale_days) || 14;

    // 🔴 An em dash, not 0 — and the difference is the whole point of these columns. `null` from the
    // server means "no basis to judge": nobody finished anything datable in the window, or the card
    // has no start. Rendering that as `0` would put a person who simply shipped nothing measurable in
    // the same red as one who missed every deadline. `??` is deliberately not used (no optional
    // chaining/nullish in this codebase's browser floor — see AGENTS.md).
    const NA = '<span class="muted">—</span>';
    const num = (v, suffix) => (v === null || v === undefined ? NA : v + (suffix || ""));

    // Load is a RELATIVE band (server-side, vs this cohort's median), never an absolute verdict —
    // tasks on this board carry no size estimate. The legend below the table says so; do not restate
    // it as "overloaded" anywhere, because the data cannot support that word.
    const BAND = { heavy: ["red", "Heavy"], steady: ["grey", "Steady"], light: ["blue", "Light"] };
    const bandPill = (r) => {
      const b = BAND[r.load_band];
      // 🔴 A bare em dash here read as a broken column, because it is what the WHOLE table showed:
      // the band is suppressed when the cohort's median open work is under two cards, and the
      // cohort used to include everybody with nothing open at all — so on any board where work is
      // concentrated on a few people the median was 0 or 1 and not one row ever got a band
      // (task_analytics.apply_load_bands). The cohort is the people carrying work now, and when a
      // band is still genuinely unavailable the dash SAYS why rather than looking like a failure.
      if (!b) return '<span class="muted" title="No band yet — this cohort\'s median open work is under two cards, so &quot;more than the median&quot; would be a single card.">—</span>';
      return `<span class="pill ${b[0]}" title="Relative to this team's median open work">${b[1]}</span>`;
    };
    // The busiest plate in the cohort on screen sets the scale for every bar — the same rule the
    // Load band already follows (compare a team against itself; AGENTS.md §5). `1` as the floor
    // keeps the arithmetic safe on a board where nobody has anything open.
    const maxOpen = Math.max(1, ...rows.map((r) => r.open_total || 0));
    // Capacity sits beside the NAME, not in its own column: "is this person even here?" changes how
    // you read every other number in the row, so it has to be seen at the same moment.
    const capacity = (r) => (r.on_leave_today
      ? '<span class="pill amber" title="Approved leave covers today">On leave</span>'
      : r.leave_days_ahead
        ? `<span class="pill grey" title="Approved leave in the next fortnight">${r.leave_days_ahead}d off soon</span>`
        : "");

    // `table-sticky-1` freezes the PERSON column (styles.css). The Monitor gained four columns in
    // 2026-08-06 and `.monitor` scrolls horizontally, so reading Cycle or On-time meant scrolling the
    // name away — and this is the table a manager STAFFS from, where "whose row is this?" is the one
    // question that must never need a scroll back.
    board.innerHTML = `<table class="mon-tbl table-sticky-1">
      ${/* 🔴 PLAIN HEADERS (2026-08-14). These read "Load / Workload / Sitting / Cycle / On time /
            Done · 7d" — six pieces of analytics jargon, three of which ("Load" vs "Workload" vs
            "Open") sound like the same thing and are not: one is a RELATIVE BAND, one is a BAR of
            open work by column, one is a COUNT. A manager staffs from this table, so a header that
            has to be hovered before it can be trusted is a header that gets guessed at instead.
            Every tooltip is kept — the header is now the short version of it rather than a code. */""}
      <thead><tr>
        <th>Teammate</th>
        <th title="How this person's open work compares with the median for this team">vs team</th>
        <th title="How much is open, and which columns it is sitting in">Open work</th>
        <th class="num" title="Open cards on this person right now">Open</th>
        <th class="num" title="Open cards whose due date has passed">Past due</th>
        <th class="num" title="Open cards nobody has touched in ${staleDays}+ days">Untouched</th>
        <th class="num" title="Median calendar days from start to completion, over the last ${MONITOR_WINDOW_DAYS} days">Days to finish</th>
        <th class="num" title="Share of dated work delivered on or before its due date, over the last ${MONITOR_WINDOW_DAYS} days">Met due date</th>
        <th class="num" title="Cards completed in the last 7 days">Finished (7d)</th>
      </tr></thead>
      <tbody>${rows.map((r) => {
        const u = r.user;
        const open = r.open_total || 0;
        const segs = barSegs.map((st) => { const n = r.counts[st] || 0; return n ? `<i class="${segCls[st]}" style="flex:${n}" title="${S.esc(st)}: ${n}"></i>` : ""; }).join("");
        // Length = how much, colour = what kind. `segs` are flex-GROW, so they only ever divide up
        // whatever width the bar is given; the width is this row's share of the busiest plate.
        const wlPct = Math.round((open / maxOpen) * 100);
        // "9 (4 as steps)" — a row that is mostly other people's cards is a different working life
        // from one that is all your own, and before 2026-08-05 those cards weren't counted at all.
        // Two sub-lines under the Open count, each answering "why is that number what it is":
        // work held via somebody else's breakdown, and work Atrium owns. The second one also warns
        // that those cards can't reach Cycle/On-time — Atrium sends no completion stamp, so counting
        // them there would mean counting completion off `updated_at` (the §2.4h bug).
        const stepNote = r.stepped ? `<span class="mon-sub" title="Cards somebody else leads, where this person owns a phase or step of the plan">${r.stepped} on steps</span>` : "";
        // 🔴 Counted and labelled SEPARATELY from `stepped` (2026-08-06). Support used to fall into
        // that bucket, so a person named on a card as support was described as owning "steps" of it —
        // possibly zero steps. The label has to match the reason or the row is confidently wrong
        // about how somebody's day is actually spent.
        const supportNote = r.supporting ? `<span class="mon-sub" title="Cards somebody else leads, where this person is named as support">${r.supporting} supporting</span>` : "";
        // 🔴 OPEN client cards, like both sub-lines above it (2026-08-06). The server sent a TOTAL
        // until then, so this line could be bigger than the Open count it hangs under.
        const clientNote = r.client_cards ? `<span class="mon-sub" title="Open client cards Atrium owns, led by this person. Atrium sends no completion date, so these cannot appear in “Days to finish” or “Met due date”.">${r.client_cards} client-owned</span>` : "";
        // 🔴 The reactive half of the plate (2026-08-11) — §1 vs §3 of the task-placement guidelines.
        // OPEN-scoped like the three sub-lines above it, because this cell is a breakdown of the Open
        // number beside it; `client_cards` shipped as a total once and produced "8 open · 19 client".
        // Unclassified work (every task predating the column, and every Atrium card) is in NEITHER
        // side, so this line can be smaller than Open without the difference being planned work.
        // "added" meant nothing on its own — every task was added by somebody. The word that carries
        // the actual distinction (§1 vs §3 of the task-placement guidelines) is UNPLANNED.
        const addedNote = r.added_open ? `<span class="mon-sub" title="Open work that came up during the day rather than being planned in ahead of it — an unexpected revision, a budget change, a report suddenly needed. Tasks raised before this was tracked count as neither planned nor unplanned.">${r.added_open} unplanned</span>` : "";
        return `<tr data-uid="${u.id}" tabindex="0">
          <td class="who"><div class="who-in">${S.avatar(u, "sm")}<div><div class="n">${S.esc(u.name)} ${capacity(r)}</div><div class="r">${S.esc(u.role_label || u.role || "")}</div></div></div></td>
          <td>${bandPill(r)}</td>
          <td class="wl"><div class="wl-track" title="${open} open of ${maxOpen} on the busiest plate here"><div class="wl-bar" style="--wl:${wlPct}%">${segs}</div></div></td>
          <td class="num">${open}${stepNote}${supportNote}${clientNote}${addedNote}</td>
          <td class="num ${r.overdue ? "bad" : ""}">${r.overdue || 0}</td>
          <td class="num ${r.stale_open ? "warn" : ""}">${r.stale_open || 0}</td>
          <td class="num">${num(r.median_cycle_days, "d")}</td>
          <td class="num ${r.on_time_rate !== null && r.on_time_rate !== undefined && r.on_time_rate < 60 ? "bad" : ""}">${num(r.on_time_rate, "%")}</td>
          <td class="num good">${r.completed_week || 0}</td>
        </tr>`;
      }).join("")}</tbody></table>
      ${/* 🔴 A DEFINITION LIST, NOT A PARAGRAPH (2026-08-14). The same facts were one 150-word block
            of prose with six bold words buried in it, so the one answer somebody actually wanted —
            "what does Sitting mean?" — had to be found by reading all of it. Every term below is now
            addressable on its own line, in the SAME wording as the column header above it, because a
            legend that renames the thing it explains is a second vocabulary to learn.

            Nothing here is a new claim: the caveats were all present in the paragraph and every one
            of them is load-bearing (a client card genuinely cannot reach the two derived columns; the
            rows genuinely do not sum to the board). Losing one to tidiness would make the table
            confidently wrong rather than merely dense. */""}
      <div class="mon-legend">
        <p class="mon-legend-top">These numbers describe <b>who is carrying what</b>. Tasks carry no
          size estimate, so nothing here measures hours — it ranks and counts cards.</p>
        <dl>
          <dt>vs team</dt>
          <dd>Whether this person has more or less open work than the team's typical person. Blank
            until the team's median reaches two cards — below that, "more than typical" is one card.</dd>

          <dt>Open work</dt>
          <dd>The bar. Its <b>length</b> is this person's open cards against the busiest plate on
            screen; its <b>colours</b> are which columns that work is sitting in.</dd>

          <dt>Open</dt>
          <dd>Cards on this person now. The small lines underneath say why that number is what it is:
            <b>on steps</b> (someone else leads the card, this person owns part of the plan),
            <b>supporting</b> (named as help, not accountable),
            <b>client-owned</b> (the card lives in Atrium), and
            <b>unplanned</b> (came up during the day rather than being planned in).</dd>

          <dt>Untouched</dt>
          <dd>Open cards nobody has changed in ${staleDays}+ days. Not necessarily late — just quiet.</dd>

          <dt>Days to finish · Met due date</dt>
          <dd>The last ${MONITOR_WINDOW_DAYS} days, and <b>Sentinel cards only</b>. Atrium never sends
            a completion date, so a person's <b>client-owned</b> cards count under Open and can never
            appear in these two columns. A dash means there was nothing to measure, not zero.</dd>
        </dl>
        <p class="mon-legend-note">🔴 <b>These rows do not add up to the board's total, and that is
          correct.</b> One card can sit on several plates — its lead, its supporters, and whoever owns
          a step of it — so shared work is counted on every plate it is really on. For the same reason
          <b>Open minus unplanned is not "planned"</b>: cards raised before this was tracked, and every
          client-owned card, are neither.</p>
      </div>`;
    const jump = (uid) => { setMode("employee"); requestAnimationFrame(() => focusLane(uid)); };
    S.qsa(".mon-tbl tbody tr").forEach((tr) => {
      tr.onclick = () => jump(tr.dataset.uid);
      tr.onkeydown = (e) => { if (e.key === "Enter") jump(tr.dataset.uid); };
    });
    renderThroughput(board);
  }

  // WP 6.2 (§2.4i): Monitor was a snapshot — no trend, no history, no per-client view. Appended
  // after the roster paints and fails SILENTLY: a trend is context, and losing it must never cost
  // a manager the workload table they came for.
  async function renderThroughput(board) {
    let data;
    try { data = await S.api("/api/tasks/throughput?weeks=8"); }
    catch (e) { return; }
    const weeks = data.weeks || [];
    if (!weeks.length) return;
    const peak = Math.max(1, ...weeks.map((w) => w.completed));
    const bars = weeks.map((w) => {
      // 🔴 The current week is PARTIAL. It is drawn, because people want to see it, but marked —
      // a 2-day week next to full ones otherwise reads as a collapse that never happened.
      const h = Math.round(100 * w.completed / peak);
      const label = w.complete ? `Week of ${w.week_start}: ${w.completed} shipped`
                               : `This week so far: ${w.completed} shipped (still running)`;
      return `<div class="tp-col" title="${S.esc(label)}">
        <div class="tp-bar${w.complete ? "" : " tp-partial"}" style="height:${Math.max(h, 2)}%"></div>
        <span class="tp-n">${w.completed}</span>
      </div>`;
    }).join("");
    const clients = (data.by_client || []).slice(0, 5).map((c) =>
      `<li><span>${S.esc(c.client_name)}</span><b>${c.completed}</b></li>`).join("");

    const wrap = document.createElement("div");
    wrap.className = "tp-wrap";
    wrap.innerHTML = `<div class="row between" style="align-items:baseline;margin:26px 0 10px">
        <div class="section-label">Throughput · last ${weeks.length} weeks</div>
        <span class="sub" style="font-size:12px">${data.weekly_average} / week on average<span class="muted"> · complete weeks only</span></span>
      </div>
      <div class="tp-chart">${bars}</div>
      ${clients ? `<div class="section-label" style="margin:22px 0 8px">Shipped by client</div>
        <ul class="tp-clients">${clients}</ul>` : ""}`;
    board.appendChild(wrap);
  }

  function focusLane(uid) {
    const lane = S.qs(`.lane[data-uid="${uid}"]`);
    if (!lane) return;
    lane.scrollIntoView({ behavior: "smooth", block: "start" });
    lane.classList.remove("flash"); requestAnimationFrame(() => lane.classList.add("flash"));
  }

  // Atrium-bridged cards (t.source === "atrium") have no local Task row -- their id is the string
  // "atrium:<client_key>:<task_id>". They open in the SAME drawer: /api/tasks/{id} reads them back
  // across the bridge and every write from the drawer is routed to Atrium. (Until 2026-07-29 this
  // showed "open it in Atrium to view or edit", which is a dead end, not an answer -- the team
  // works this board, so the board has to edit the work.)
  function openTask(id) {
    openDetail(id);
  }

  function wireCardClicks() {
    // Some browsers still dispatch a click on the source element right after a completed native
    // drag (the "dragging" class is already gone by then, since dragend clears it synchronously) --
    // wireDnD also stamps a short-lived data-just-dragged flag so that trailing click is swallowed
    // instead of reopening the drawer on the card that was just moved.
    S.qsa(".tcard").forEach((c) => c.onclick = () => { if (!c.classList.contains("dragging") && !c.dataset.justDragged) openTask(c.dataset.id); });
    // The hover ✕ deletes in place (confirm first — deletion is irreversible). stopPropagation
    // so the click doesn't also open the detail drawer.
    S.qsa(".t-del").forEach((b) => b.onclick = (e) => {
      e.stopPropagation();
      const t = allTasks.find((x) => String(x.id) === b.dataset.del);
      if (t) confirmDelete(t);
    });
  }

  // "Today" in Manila as an ISO date (en-CA → YYYY-MM-DD), so due-date colouring matches the
  // server's Asia/Manila business rule instead of the viewer's local timezone.
  const PH_TODAY = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Manila" });
  // Minutes → "1h 30m" / "45m" for the record's Time fact (sessions + estimate).
  function fmtMins(m) {
    m = Math.max(0, Math.round(+m || 0));
    return m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
  }

  function dueClass(due) {
    if (!due) return "";
    if (due < PH_TODAY) return "over";
    const days = (Date.parse(due + "T00:00:00Z") - Date.parse(PH_TODAY + "T00:00:00Z")) / 864e5;
    return days <= 2 ? "soon" : "";
  }

  // How many days late, for the one card it applies to. Positive only — the date itself already
  // says "soon" for anything not yet due.
  const daysLate = (due) => Math.round(
    (Date.parse(PH_TODAY + "T00:00:00Z") - Date.parse(due + "T00:00:00Z")) / 864e5);

  // 🔴 SITTING IN THE PARKED COLUMN *IS* THE HOLD — `on_hold` alone was never the question
  // (2026-08-14). `task_workflow._sync_hold` made that true on both sides of every Sentinel move, so
  // the two can only disagree on a card whose `on_hold` this board does not write:
  //
  //   an ATRIUM card — moving one parks nothing. `PATCH /{id}/status` takes the Atrium branch and
  //                    calls `atrium_tasks.move_task`, which moves the STAGE and only the stage;
  //                    over there `on_hold` is a separate flag of Atrium's own, tested
  //                    independently of the column (its `report_ai` asks `stage == "blocked" OR
  //                    on_hold`). So a client card reaches this column with `on_hold` false.
  //   a legacy row   — dragged into the column before `_sync_hold` shipped and untouched since.
  //
  // Both then rendered as ordinary live work sitting in the Parked column: no PARKED flag, no
  // dashed quiet card, nothing at a glance to separate them from In Progress next door — which is
  // exactly the "two kinds of parked card that behave differently" `_sync_hold` was written to end,
  // surviving in the half of the board it could not reach.
  //
  // By STAGE, never the label: Manage renames that column (D13).
  const isParked = (t) => !!t.on_hold || STAGE_OF[t.status] === "blocked";

  // 🔴 ONE FLAG PER CARD. This ladder IS the "say the important thing" rule, in one place: the
  // worst true thing wins and everything else stays quiet and lives in the record. It replaces a
  // row of five pills (parked / review / approved / changes / stale) that could all be on at once,
  // on a card 288px wide — at which point none of them was read.
  //
  // 🔴 OVERDUE IS DELIBERATELY NOT IN THIS LADDER. The DATE carries it, in red, at the other end
  // of the card. Returning it here spends the flag slot on something already said, which is how
  // the one card that was both late AND had an open client change request showed only "late" —
  // the worse of its two problems hid the actionable one.
  function flagOf(t, done) {
    if (done) return null;
    if (t.open_changes) return { t: "Client asked", c: "bad" };
    if (t.atrium_sync_error) return { t: "Not synced", c: "bad" };
    if (t.review_state === "pending") return { t: "In review", c: "warn" };
    if (t.review_state === "changes_requested") return { t: "Changes", c: "warn" };
    if (t.review_state === "approved") return { t: "Approved", c: "" };
    if (t.priority === "Urgent") return { t: "Urgent", c: "bad" };
    if (isParked(t)) return { t: "Parked", c: "" };
    if (t.archived) return { t: "Filed", c: "" };
    // Bottom rung: routed to a department, owned by nobody. On a manager's board it is work that
    // needs staffing; on a team member's it is the one card there that is not theirs (the team
    // queue, task_perms._team_queue), and without the word it just looks like a card missing a face.
    if (!t.assigned_to_id && t.assigned_team_id) return { t: "Unclaimed", c: "" };
    return null;
  }

  // Filing only makes sense at the two ends: a finished task can be filed, a filed one can come
  // back. Unfinished work that has to leave the board gets PARKED — the server refuses to file it.
  function filingBtn(t, done) {
    if (t.archived) return `<button class="btn ghost" id="d-unarchive">Back on the board</button>`;
    return done ? `<button class="btn ghost" id="d-archive">File to Past work</button>` : "";
  }

  // The bridge control. The two kinds of card mean OPPOSITE things here, which is why one shape
  // could never serve both:
  //
  //   an Atrium card  — already in Atrium. The control is a real TOGGLE: it flips whether the client
  //                     sees the card on their Progress tab, and flipping it back is meaningful.
  //   a Sentinel row  — pushed one way, client-safe fields only. Once published there is no un-share
  //                     (nothing deletes a card the client has already seen), so a shared row has no
  //                     action left to offer.
  //
  // 🔴 So a shared Sentinel row renders NOTHING here (2026-08-06). "✓ Shared with the client" was a
  // `btn` and stayed clickable: it read as a state, and clicking it silently re-published and wrote
  // another AtriumApproval row. (`task_bridge.publish` is idempotent, so it never created a second
  // card — it was misleading, not destructive.) It became a chip, and then went altogether when the
  // footer moved behind More: a state does not belong in an actions menu, and the record says it
  // twice already — the modal's kicker ends "· shared with the client", and the internal field list
  // carries "Client card · Published". Re-pushing happens automatically on every edit that touches a
  // client-visible field, and a push that FAILED has its own Retry, so there is nothing to press.
  //
  // 🔴 And an unshared row with NO CLIENT gets a disabled button, not a live one. `publish()` returns
  // "That task has no Atrium client linked" for it every time, so the button could only ever 502 —
  // the one thing this file says a control must never do ("so the bar never promises a 403").
  // Disabled-with-a-reason rather than hidden: a manager looking for the share control deserves to
  // find out WHY it can't be used, not to wonder where it went.
  function atriumControl(t, isAtrium) {
    if (isAtrium) {
      return `<button class="btn ghost" id="d-atrium">${t.atrium_visible
        ? "✓ Client can see this" : "Share with client"}</button>`;
    }
    if (t.atrium_shared) return "";
    if (!t.client_id) {
      return `<button class="btn ghost" id="d-atrium" disabled
        title="This task has no client, so there is no workspace to share it into. Set a client under Edit → More options first.">Share with the client</button>`;
    }
    return `<button class="btn ghost" id="d-atrium">Share with the client</button>`;
  }

  // The support avatars, beside the lead's. Overlapped rather than laid out in a row: a card is 288px
  // wide and four full avatars with names would push the status pills off the end. Capped at three
  // with a "+N", which is what makes a card with eight people on it still read as one card.
  //
  // 🔴 Works for BOTH kinds of card, and since 2026-08-06 from the SAME field. `support` is now
  // published for a client card too: the server resolves each Atrium roster email to the Sentinel
  // user who is that person (`services/atrium_identity`, the same ladder the lead has used since
  // 2026-08-05), so a supporter with a photo finally shows it instead of grey initials beside a
  // lead who had one. Anyone who does NOT resolve arrives as an id-less name and still renders —
  // named, never faked. `atrium_support_names` stays as the fallback for a payload built without a
  // resolver, and reading only one of the two would silently hide support on half the board.
  const supportOf = (t) => ((t.support || []).length
    ? t.support
    : (t.atrium_support_names || []).map((n) => ({ id: null, name: n })));

  function supportStack(t) {
    const people_ = supportOf(t);
    if (!people_.length) return "";
    const shown = people_.slice(0, 3);
    const extra = people_.length - shown.length;
    const all = people_.map((p) => p.name).join(", ");
    return `<span class="t-support" title="Support: ${S.esc(all)}">`
      + shown.map((p) => S.avatar(p, "tb-md" + (p.id === S.user.id ? " is-me" : ""))).join("")
      + (extra ? `<span class="t-support-more">+${extra}</span>` : "")
      + `</span>`;
  }

  // `laneUid` is set only in By Employee, where the same card appears in several lanes. It is what
  // lets the card say WHICH hat this lane's person wears on it — without that, a supporter's lane
  // silently lists work whose Lead reads another name, which is indistinguishable from the July 2026
  // regression where a board showed other people's work.
  function card(t, laneUid) {
    const done = isDoneStatus(t.status);
    const dueCls = dueClass(t.due_date);
    const flag = flagOf(t, done);
    const laneSupports = laneUid != null && laneUid !== "none"
      && Number(laneUid) !== t.assigned_to_id
      && (t.support_ids || []).indexOf(Number(laneUid)) >= 0;
    // An Atrium-owned card cannot be bulk-edited (it lives in another system and the endpoint
    // refuses composite ids), so it never gets a checkbox — better than offering one that only
    // ever produces a skip.
    const pickable = selecting && !String(t.id).startsWith("atrium:");
    // The label is a 6px DOT in the client's colour, not a filled pill: within a client it almost
    // never varies, so as a pill it was the loudest thing on the board while saying the least.
    // Its title attribute is what still names it, and the record spells it out in full.
    const label = t.labels && t.labels[0];
    // 🔴 The date is where "late" is said, and the only place. Finished work shows the day it
    // SHIPPED (green) instead — on a done card a due date is a promise nobody is waiting on.
    const dateBit = done
      ? `<span class="ship" title="Completed">${S.fmtDate(t.completed_at || (t.due_date && t.due_date + "T00:00:00+08:00"))}</span>`
      : (t.due_date
        ? `<span class="${dueCls}" title="Due ${S.esc(S.fmtDateFull(t.due_date + "T00:00:00+08:00"))}">${S.fmtDate(t.due_date + "T00:00:00+08:00")}${
            dueCls === "over" ? ` · ${daysLate(t.due_date)}d late` : ""}</span>`
        : "");
    const pct = t.checklist_total ? Math.round(100 * t.checklist_done / t.checklist_total) : 0;
    const camp = campaignOf(t);
    // 🔴 A card can now be VISIBLE-BUT-NOT-YOURS (2026-08-14): an employee's board carries their whole
    // department. Such a card must not be draggable, must not offer the move select, and must not be
    // selectable for a bulk action — every one of those would answer 403 on drop, which is the "the
    // button is broken" experience this release exists to remove. It still opens: reading a
    // colleague's card is the entire point of showing it.
    const editable = canEditCard(t);
    return `<div class="tcard${isParked(t) ? " quiet" : ""}${editable ? "" : " readonly"}" draggable="${editable}" data-id="${t.id}"${
        editable ? "" : ` title="${S.esc((t.assignee && t.assignee.name) || "Somebody else")} owns this — you can open it, but only they or a lead can change it"`}>
      <div class="t-top">
        ${(pickable && editable) ? `<input type="checkbox" class="t-pick" aria-label="Select ${S.esc(t.title)}">` : ""}
        ${label ? `<span class="t-disc" style="background:${S.esc(S.colors.labels[label] || "#6B7280")}" title="${S.esc(t.labels.join(", "))}"></span>` : ""}
        <span class="t-client">${S.esc(t.client_name || "Internal")}</span>
        ${/* Client / campaign reads as one line, which is also the naming rule the form now states:
              the client is printed HERE, above the title, so it does not belong in the title, and the
              campaign is printed here so it does not have to be repeated in the title either. */
          camp ? `<span class="t-camp" title="Campaign — ${S.esc(camp)}">${S.esc(camp)}</span>` : ""}
        ${laneSupports ? `<span class="t-hat" title="Supporting — ${S.esc((t.assignee && t.assignee.name) || "somebody else")} leads this card">supporting</span>` : ""}
        ${flag ? `<span class="t-flag ${flag.c}">${flag.t}</span>` : ""}
        ${canDelete(t) ? `<button class="t-del" data-del="${t.id}" title="Delete task" aria-label="Delete task">✕</button>` : ""}
      </div>
      <div class="t-title">${S.esc(t.title)}</div>
      <div class="t-foot">
        <div class="t-people"${t.source === "atrium" && t.assignee ? ` title="Lead on the client's Atrium card — Atrium's roster, not a Sentinel account"` : ""}>
          ${S.avatar(t.assignee, t.assignee
            ? "tb-md is-lead" + (t.assignee.id === S.user.id ? " is-me" : "")
            : "tb-md")}${supportStack(t)}
          ${/* Unowned work has to SAY so — a lone grey "?" disc reads as a missing photo, not as a
                card nobody has picked up. */
            t.assignee ? "" : `<span class="t-unassigned">Unassigned</span>`}
        </div>
        <div class="t-meta">${dateBit}${t.comment_count ? `<span class="cc" title="${t.comment_count} comment${t.comment_count > 1 ? "s" : ""}">${S.ICON.comment}${t.comment_count}</span>` : ""}</div>
      </div>
      ${t.checklist_total ? `<div class="t-bar" title="${t.checklist_done} of ${t.checklist_total} steps done"><i style="width:${pct}%"></i></div>` : ""}
      ${editable ? `<select class="t-move" data-move="${t.id}" aria-label="Move ${S.esc(t.title)} to another column">${moveOptions(t.status)}</select>` : ""}</div>`;
  }

  // The move control has to be able to show where the card IS, even when that is a status the board
  // no longer offers (see columnsFor). Without its own status in the list a stranded card's select
  // silently displayed the FIRST column instead — so it read as "To Do" while sitting somewhere
  // else, and the equality guard in wireMoveSelects would swallow the first attempt to move it.
  function moveOptions(current) {
    const list = STATUSES.indexOf(current) < 0 ? [current].concat(STATUSES) : STATUSES;
    return list.map((s) => `<option ${s === current ? "selected" : ""}>${S.esc(s)}</option>`).join("");
  }

  // The mobile/keyboard twin of drag-and-drop (WP 5.5). It routes through the SAME `moveCard`, so
  // the optimistic reposition, the Undo toast and the roll-back on failure are identical however
  // the move was made — there is no second move path to keep in step.
  function wireMoveSelects(opts = {}) {
    S.qsa(".t-move").forEach((sel) => {
      // Interacting with the control must never open the card underneath it.
      sel.onclick = (e) => e.stopPropagation();
      sel.onchange = (e) => {
        e.stopPropagation();
        const cardEl = sel.closest(".tcard");
        const fromList = cardEl.closest(".col-list");
        if (!fromList || fromList.dataset.status === sel.value) return;
        // In swimlanes every lane repeats the same columns, so the target has to be matched
        // WITHIN this card's lane — otherwise the card would jump to another person's row, which
        // is a reassignment, and those belong in the drawer (same rule wireDnD enforces).
        const scope = opts.sameLane ? cardEl.closest(".lane") : document;
        const toList = [...scope.querySelectorAll(".col-list")]
          .find((l) => l.dataset.status === sel.value);
        if (!toList) return;
        moveCard(cardEl, toList, sel.value, fromList, fromList.dataset.status);
      };
    });
  }

  function wireDnD(opts = {}) {
    let dragEl = null;
    S.qsa(".tcard").forEach((c) => {
      // A read-only department card carries draggable="false" (see the card template), so it never
      // starts a drag — but wire nothing to it either, so a browser that ignores the attribute
      // cannot smuggle one through.
      if (c.classList.contains("readonly")) return;
      c.ondragstart = (e) => { dragEl = c; c.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; };
      c.ondragend = () => {
        c.classList.remove("dragging");
        S.qsa(".col.drag-over").forEach((x) => x.classList.remove("drag-over"));
        // See wireCardClicks: swallow exactly one trailing click, in case this browser fires one
        // after the drag instead of suppressing it.
        c.dataset.justDragged = "1";
        setTimeout(() => { delete c.dataset.justDragged; }, 0);
      };
    });
    S.qsa(".col-list").forEach((list) => {
      const col = list.closest(".col");
      list.ondragover = (e) => { e.preventDefault(); col.classList.add("drag-over"); };
      list.ondragleave = (e) => { if (!list.contains(e.relatedTarget)) col.classList.remove("drag-over"); };
      list.ondrop = (e) => {
        e.preventDefault(); col.classList.remove("drag-over");
        if (!dragEl) return;
        const fromList = dragEl.closest(".col-list");
        // In swimlanes, only allow moves within the same person's lane (status change, not reassign).
        const sameLane = !opts.sameLane || fromList.dataset.uid === list.dataset.uid;
        if (fromList !== list && sameLane) moveCard(dragEl, list, list.dataset.status, fromList, fromList.dataset.status);
        dragEl = null;
      };
    });
  }

  // Recount every column header from the DOM (after an optimistic move).
  function updateCounts() {
    S.qsa(".col").forEach((col) => {
      const c = col.querySelector(".col-head .c");
      if (c) c.textContent = col.querySelectorAll(".col-list > .tcard").length;
    });
  }

  // Optimistic move: reposition the card immediately, sync in the background, roll back on failure.
  async function moveCard(cardEl, toList, toStatus, fromList, fromStatus, opts = {}) {
    const id = cardEl.dataset.id;
    toList.appendChild(cardEl);
    // Keep the card's own move control showing where the card now IS. Without this a drag (or an
    // Undo) leaves the select reading the previous column, and the next change event can look
    // like a no-op and be swallowed by the equality guard in wireMoveSelects.
    const sel = cardEl.querySelector(".t-move");
    if (sel) sel.value = toStatus;
    updateCounts();
    cardEl.classList.remove("just-moved");
    requestAnimationFrame(() => cardEl.classList.add("just-moved"));   // restart the flash
    try {
      await S.api(`/api/tasks/${id}/status`, { method: "PATCH", body: { status: toStatus } });
      if (!opts.silent) {
        // 🔴 UNDO RE-RESOLVES THE DOM. It used to close over `cardEl`/`fromList`, which are only
        // valid until the next render — and this board re-renders on its own, from the SSE `task`
        // event, 400ms after anyone else touches anything. Clicking Undo then moved a DETACHED node:
        // the PATCH landed, so the card really did go back, but the board on screen still showed it
        // in the new column until the next load. Looking the id up at CLICK time means Undo either
        // finds the live card or does the move without a stale animation, never against a ghost.
        S.toast("Moved to " + toStatus, "ok", { action: { label: "Undo", onClick: () => undoMove(id, fromStatus) } });
      }
    } catch (err) {
      fromList.appendChild(cardEl);   // roll back the optimistic move
      updateCounts();
      S.toast(err.detail || "Couldn't move task", "err");
    }
  }

  // Undo, resolved against the board as it is NOW rather than as it was when the toast appeared.
  // Falls back to a plain PATCH + reload when the card is no longer rendered (a filter changed, or
  // the move took it out of view) — the move must still happen; only the animation is optional.
  async function undoMove(id, toStatus) {
    const cardEl = S.qs(`.tcard[data-id="${id}"]`);
    const toList = cardEl
      ? [...(cardEl.closest(".lane") || document).querySelectorAll(".col-list")]
        .find((l) => l.dataset.status === toStatus)
      : null;
    if (cardEl && toList) {
      const fromList = cardEl.closest(".col-list");
      moveCard(cardEl, toList, toStatus, fromList, fromList.dataset.status, { silent: true });
      return;
    }
    try {
      await S.api(`/api/tasks/${id}/status`, { method: "PATCH", body: { status: toStatus } });
      load();
    } catch (err) { S.toast(err.detail || "Couldn't undo that move", "err"); }
  }

  // "Add card" at the foot of each column opens the SAME full form as Edit (not an inline
  // title box), pre-set to that column's status. Nothing is forced — a blank name saves as
  // "Untitled task" and can be renamed later.
  function wireAddButtons() {
    S.qsa(".col-add").forEach((btn) => btn.onclick = () => taskForm(null, btn.dataset.status));
  }

  // --- Opening a task -----------------------------------------------------------------------------
  // A wide centred modal (see the CSS note above for why not a docked panel). The URL still carries
  // `?open=<id>` — that is the param every task notification uses, so a shared link, a notification
  // and a click all land on the same card, and refreshing keeps the task open.
  function setOpenParam(id) {
    const u = new URLSearchParams(location.search);
    if (id) u.set("open", id); else u.delete("open");
    // replaceState, not pushState: opening six cards in a row must not bury the page under six
    // back-button steps.
    history.replaceState(null, "", location.pathname + (u.toString() ? "?" + u : ""));
  }

  // 🔴 `onClose` — ONE hook, instead of re-pointing three closers (2026-08-06).
  // This used to re-point S.modal's ✕ and backdrop by hand and register its own Escape listener,
  // because S.modal called its internal close directly and wrapping the returned `close` missed
  // those paths. It missed some anyway: the Escape listener was only removed if Escape was pressed
  // (so it leaked one per card opened), and nothing covered the case that actually bit — a NESTED
  // modal (Park, Request changes, Delete) closing the card underneath it. `?open=<id>` then stayed
  // in the URL with no card on screen, and a refresh reopened a card the user had cancelled out of.
  // S.modal now fires `onClose` on every path, and a nested modal no longer closes this one at all.
  function openTaskModal(title, body, footer, id) {
    setOpenParam(id);
    return S.modal({ title, body, footer, wide: true, onClose: () => setOpenParam(null) });
  }

  async function openDetail(id) {
    let t;
    try { t = await S.api("/api/tasks/" + id); }
    catch (err) { S.toast(err.detail || "Couldn't open that task", "err"); return; }
    if (!Array.isArray(t.maintasks)) t.maintasks = [];
    // An Atrium-owned card opens in this SAME drawer, with Atrium's vocabulary: its owners come
    // from ATRIUM's roster (ids are login emails, not Sentinel user ids) and it has fields Sentinel
    // rows don't (department, lead/support, start date, hold, client visibility), so those render
    // from the atrium_* values the bridge sent. Every write below is routed back to Atrium by
    // /api/tasks/{id} — nothing about the card is stored here.
    const isAtrium = t.source === "atrium";
    const owners = isAtrium ? (t.atrium_roster || []) : people;
    const ownerId = (v) => (isAtrium ? (v || "") : (v ? +v : null));
    // Priority is a management call (task_perms.can_prioritize), so it is a CONTROL for a manager
    // and a plain value for everyone else — never a control that can only answer 403.
    const prioritySelect = canPrioritize(t)
      ? `<select id="d-priority">${vocab.priorities.map((p) => `<option ${p === t.priority ? "selected" : ""}>${p}</option>`).join("")}</select>`
      : `${S.priorityDot(t.priority)}${S.esc(t.priority)}`;
    const done = isDoneStatus(t.status);
    const overdue = !!t.due_date && !done && dueClass(t.due_date) === "over";
    // 🔴 WHAT THE CLIENT ASKED FOR, WHERE YOU ACTUALLY LOOK (2026-08-04).
    // The reverse channel (D4) delivered correctly from day one, and the card even showed a red
    // "1 change request" pill — but a pill is a COUNT. The words themselves went into the comment
    // thread, in the right-hand column, below the work breakdown, styled identically to a
    // colleague's note. So the board told you a client wanted something changed and never told you
    // WHAT, which is the one thing the team needs in order to act.
    //
    // Two reasons it was invisible rather than merely buried, both worth knowing before touching this:
    //   * `cmt()` renders a red "Changes requested" pill + a resolve button off `c.kind === "changes"`
    //     — but `kind` only exists on an ATRIUM-owned card (atrium_tasks.as_task_detail). A Sentinel
    //     row's comment comes from `serializers.comment_dict`, which has no `kind` to give: the
    //     receiver bumps `tasks.client_changes_open` and does not persist the kind per comment.
    //     So the flag is TASK-level, and the honest UI for it is task-level too — this banner.
    //   * `is_client` was exposed by the serializer, documented there as "what the UI keys off",
    //     and used by NOTHING. It is used now, both here and in `cmt()`.
    // The body shown is the newest client comment, which is what the counter refers to in practice.
    // Resolve posts to /resolve-client-changes (the TASK-level endpoint) — NOT the per-comment
    // Atrium route `wireResolve` uses, which does not exist for a Sentinel row.
    const clientSaid = (t.comments || []).filter((c) => c.is_client);
    const lastClient = clientSaid.length ? clientSaid[clientSaid.length - 1] : null;
    // Park REMEMBERS the column the card left (tasks.resume_to), so say where Resume will put it —
    // otherwise the button is a guess. An Atrium card's hold has no such memory to show.
    const resumeHint = (!isAtrium && t.resume_to)
      ? `Resume puts it back in ${S.esc(t.resume_to)}.` : "";
    // 🔴 ONE NOTICE — the worst true thing, the same ladder the card's flag uses (2026-08-06).
    // This replaced a row of up to TEN chips plus two stacked warning boxes. Every one of them was
    // true, which is exactly why the row said nothing: "Shared with the client · On hold · Awaiting
    // approval · 1 change request" is four states competing for one glance, and the one that needed
    // acting on had no more weight than the three that did not. The rest is not lost — it is in the
    // facts strip, the crew row and the record below, where a reader goes looking for it.
    //
    // 🔴 IT REPORTS WHICH RUNG IT USED (`noticeKind`), and one reader depends on that. A card can be
    // parked AND late, in which case "6 days past due" wins the notice and the hold REASON — the one
    // piece of prose nothing else on this screen carries — would disappear entirely. So the internal
    // field list prints it whenever the notice did not. Say it exactly once, wherever it fits: the
    // alternative (print it in both places, always) is how a record starts repeating itself.
    const note = (cls, html) => `<div class="tb-note ${cls}">${html}</div>`;
    const noticeKind = t.open_changes ? "changes"
      : (!isAtrium && t.atrium_sync_error) ? "stale"
      : (!isAtrium && t.atrium_visible && !t.atrium_shared) ? "phantom"
      : overdue ? "overdue"
      : t.review_state === "pending" ? "review"
      : t.review_state === "changes_requested" ? "rework"
      : isParked(t) ? "parked"
      : t.archived ? "filed"
      : t.review_state === "approved" ? "approved"
      : "";
    // Keyed by the rung above, never re-tested here — two ladders in two shapes is how the notice
    // and the thing that reads it come to disagree.
    const NOTICES = {
      changes: () => note("bad", `<b>The client asked for changes.</b>`
        + (lastClient
          ? `<div class="say">“${S.esc(String(lastClient.body || "").replace(/\n?\[atrium:[^\]]*\]/g, "").trim())}”</div>
             <div class="meta">${S.esc(lastClient.author ? lastClient.author.name : "The client")} · ${S.timeAgo(lastClient.created_at)}</div>`
          : `<div class="meta">Their message is in the conversation.</div>`)
        // Sentinel rows only: /resolve-client-changes clears the TASK-level counter. An Atrium
        // card resolves ONE comment at a time, from the comment itself (wireResolve).
        + (isAtrium ? "" : `<div class="act"><button class="btn sm ghost" id="d-resolve-changes">Mark as handled</button></div>`)),
      // The projection's state, said out loud. A push that failed leaves the CLIENT's copy stale
      // while ours is current, and a pre-fix row claims a share that never happened — neither may
      // look like a healthy share (AGENTS.md §5, "Send to Atrium used to publish NOTHING").
      stale: () => note("bad", `<b>The client's copy is out of date.</b>
        <div class="say">${S.esc(t.atrium_sync_error)}</div>
        <div class="meta">Your edits saved here — press <em>Retry the client push</em> (under More) to send them.</div>`),
      phantom: () => note("bad", `<b>This was never actually shared.</b>
        <div class="meta">It is flagged as shared but no client card exists — a row predating the
        2026-08-03 fix. Press <em>Share with the client</em> (under More) to create it for real.</div>`),
      overdue: () => note("bad", `<b>${daysLate(t.due_date)} day${daysLate(t.due_date) === 1 ? "" : "s"} past due.</b>
        <div class="meta">Due ${S.fmtDateFull(t.due_date + "T00:00:00+08:00")}.</div>`),
      review: () => note("warn", `<b>Waiting on approval.</b>
        <div class="meta">${S.esc((t.assignee && t.assignee.name) || "Somebody")} submitted this for review.</div>`),
      rework: () => note("warn", `<b>Changes were requested.</b>
        <div class="meta">The reviewer's note is in the conversation.</div>`),
      parked: () => note("", `<b>Parked.</b>${t.hold_reason ? `<div class="say">${S.esc(t.hold_reason)}</div>` : ""}
        ${resumeHint ? `<div class="meta">${resumeHint}</div>` : ""}`),
      filed: () => note("", `<b>Filed to Past work.</b>
        <div class="meta">Off the board, and still counted as shipped.</div>`),
      approved: () => note("", `<b>Approved${t.reviewer ? ` by ${S.esc(t.reviewer.name)}` : ""}.</b>
        <div class="meta">It can be completed.</div>`),
    };
    const notice = NOTICES[noticeKind] ? NOTICES[noticeKind]() : "";

    // WHO IS ON THIS, before the facts: it is the question the board could not answer, and the
    // first thing anyone opening a card looks for. Both kinds of card answer it from their own
    // field (§2) — a Sentinel row has real users, an Atrium card has its roster's names.
    const sup = supportOf(t);
    const slotsOf = (pid) => (t.maintasks || []).reduce((n, m) =>
      n + (m.assignee_id === pid ? 1 : 0) + m.subs.filter((s) => s.assignee_id === pid).length, 0);
    const leadName = isAtrium
      ? (t.atrium_lead_name || t.atrium_lead_id || (t.assignee && t.assignee.name))
      : (t.assignee && t.assignee.name);
    const crew = `<div class="tb-crew">
      <div class="lead">
        ${S.avatar(t.assignee, t.assignee
          ? "tb-lg is-lead" + (t.assignee.id === S.user.id ? " is-me" : "") : "tb-lg")}
        <div>
          <div class="nm">${S.esc(leadName || "Unassigned")}</div>
          <div class="rl">Lead${t.assigned_team_name ? ` · ${S.esc(t.assigned_team_name)}` : ""}${
            /* An Atrium card's owner is a roster EMAIL, not a Sentinel account — say so, or the
               face reads as a colleague whose profile you could open. */
            isAtrium ? " · from Atrium's roster" : ""}</div>
        </div>
      </div>
      ${sup.length ? `<div class="bar"></div>` : ""}
      <div class="sup">${sup.length
        ? sup.map((p) => {
          const n = p.id ? slotsOf(p.id) : 0;
          return `<span class="sup-p">${S.avatar(p, "tb-md" + (p.id === S.user.id ? " is-me" : ""))}
            <span><span class="nm">${S.esc(p.name)}</span>${n
              ? `<br><span class="st">${n} step${n > 1 ? "s" : ""}</span>` : ""}</span></span>`;
        }).join("")
        : `<span class="none">No support yet.</span>`}</div>
      ${/* Naming somebody else on a card is DELEGATION, and the server is what enforces it
            (routers/tasks._support_delegates). Adding or removing YOURSELF is always allowed, so
            the button is offered to everyone who can edit — it opens the same form the Support
            field lives in, which lists only the people this seat may actually pick. */
        (!isAtrium && !readOnly)
          ? `<button class="btn sm ghost" id="d-add-support">+ Add support</button>` : ""}
    </div>`;

    // FOUR FACTS. The rest of the record is below and does not need a box — and none of these four
    // is repeated down there, because a record that prints its due date twice, two inches apart,
    // reads as longer than it is and the reader stops trusting either copy.
    const stageColor = (S.colors.statuses || {})[t.status];
    const dueCls = done ? "" : dueClass(t.due_date);
    const facts = [
      ["Stage", `<span class="dot" style="background:${S.esc(stageColor || "#8A939F")}"></span>${S.esc(t.status)}`, ""],
      [done ? "Delivered" : (isAtrium ? "Launch date" : "Due"),
        done
          ? S.fmtDateFull(t.completed_at || (t.due_date ? t.due_date + "T00:00:00+08:00" : null))
          : (t.due_date ? S.fmtDateFull(t.due_date + "T00:00:00+08:00") : "No date"),
        dueCls === "over" ? "bad" : dueCls === "soon" ? "warn" : ""],
      // Filled in by renderBreakdown, which owns every count of the breakdown there is.
      ["Progress", `<span id="d-bd-count"></span>`, ""],
      ["Priority", prioritySelect, t.priority === "Urgent" ? "bad" : ""],
      // TIME (2026-09-02): recorded Start Work sessions against the estimate. Sentinel rows only — an
      // Atrium card has neither. `session_minutes` is the server's sum; the running session ticks in
      // the footer, not here, so this stays a fact and not a clock.
      ...(isAtrium ? [] : [["Time",
        `${fmtMins(t.session_minutes || 0)}${t.estimate_minutes ? ` <span class="muted">/ ~${fmtMins(t.estimate_minutes)}</span>` : ""}`,
        (t.estimate_minutes && (t.session_minutes || 0) > t.estimate_minutes) ? "warn" : ""]]),
    ].map((f) => `<div><div class="k">${f[0]}</div><div class="v ${f[2]}">${f[1]}</div></div>`).join("");
    // 🔴 THE THREE PANES ARE ALL IN THE DOM, toggled with [hidden] — never re-rendered on a tab
    // click. The breakdown alone wires eight handlers per row (and re-wires itself after every
    // save), the comment box owns an input the user may be halfway through, and `wireResolve`
    // binds inside the thread: rebuilding a pane would silently drop all of it. Tabs are a
    // VISIBILITY control here, nothing more.
    const body = `<h2 class="tb-h">${S.esc(t.title)}</h2>
      ${notice}
      ${crew}
      <div class="tb-facts">${facts}</div>
      <div class="tb-cols">
      <div>
        ${t.description ? `<div class="sub" style="margin:0 0 16px">${S.esc(t.description)}</div>` : ""}
        <dl class="tb-kv">
          <dt>Client</dt><dd>${S.esc(t.client_name || "—")}</dd>
          <dt>Started</dt><dd>${t.start_date ? S.fmtDateFull(t.start_date + "T00:00:00+08:00") : "—"}</dd>
          ${/* Optional grouping field — shown only when set, so a task that is not part of a
                campaign does not carry an empty row. Through `campaignOf` since 2026-08-11, which is
                also what stops a pre-2026-08-04 task echoing its own title back into this row: those
                rows really do hold `campaign === title` and were deliberately never backfilled. */
            campaignOf(t) ? `<dt>Campaign</dt><dd>${S.esc(campaignOf(t))}</dd>` : ""}
          ${t.project ? `<dt>Project</dt><dd><a href="/projects?project=${t.project.id}">${S.esc(t.project.name)}</a></dd>` : ""}
          ${/* 🔴 Shown ONLY when classified. A task raised before this column existed, and every
                Atrium card (no Sentinel creator to judge), genuinely has no answer — and printing
                "Planned" on those would be the on-time-rate-as-0 mistake in another field. */
            ORIGIN_LABEL[t.origin]
              ? `<dt>Raised</dt><dd>${ORIGIN_LABEL[t.origin]}</dd>` : ""}
          ${t.content_type ? `<dt>Content type</dt><dd>${S.esc(t.content_type)}</dd>` : ""}
          ${t.deliverable_url ? `<dt>Deliverable</dt><dd><a href="${S.esc(t.deliverable_url)}" target="_blank">Open →</a></dd>` : ""}
        </dl>
        ${t.client_facing_notes ? `<div style="margin-top:14px"><div class="section-label">${isAtrium ? "Client note" : "Client notes"}</div><div class="sub" style="margin-top:5px">${S.esc(t.client_facing_notes)}</div></div>` : ""}
        <div style="margin-top:20px;padding-top:15px;border-top:1px solid var(--line-soft)">
          <div class="section-label" style="color:var(--sentinel-2)">${S.ICON.lock}Internal — never seen by the client</div>
          <dl class="tb-kv" style="margin-top:10px">
            <dt>Department</dt><dd>${S.esc(t.assigned_team_name || "—")}${
              (!t.assigned_to_id && t.assigned_team_id) ? ` <span class="muted">· unclaimed queue</span>` : ""}</dd>
            ${isAtrium ? `
              <dt>Shared with client</dt><dd>${t.atrium_visible ? "Yes — on their Progress tab" : "No — internal only"}</dd>
              ${t.reporter === "client" ? `<dt>Raised by</dt><dd>${S.esc(t.reporter_name || "the client")}</dd>` : ""}
            ` : `
              <dt>Filed by</dt><dd>${S.esc(t.created_by ? t.created_by.name : "—")}</dd>
              <dt>Account manager</dt><dd>${S.esc(t.account_manager ? t.account_manager.name : "—")}</dd>
              ${t.service_charge_label ? `<dt>Service charge</dt><dd>${S.esc(t.service_charge_label)}</dd>` : ""}
              ${t.atrium_shared ? `<dt>Client card</dt><dd>Published — client-safe fields re-sent on every edit</dd>` : ""}
            `}
            ${t.labels && t.labels.length ? `<dt>Labels</dt><dd>${S.labelPills(t.labels)}</dd>` : ""}
          </dl>
          ${/* The hold reason, but ONLY when a worse notice took the top of the record (a card can
                be parked AND late). It is the one piece of prose no other surface carries — the
                card shows a "Parked" flag, the facts strip shows the column, neither can say why. */
            (t.on_hold && t.hold_reason && noticeKind !== "parked")
              ? `<div style="margin-top:12px"><div class="section-label">Parked because${resumeHint ? " · " + resumeHint : ""}</div><div class="sub" style="margin-top:5px">${S.esc(t.hold_reason)}</div></div>` : ""}
          ${t.internal_notes ? `<div style="margin-top:12px"><div class="section-label">Internal notes</div><div class="sub" style="margin-top:5px">${S.esc(t.internal_notes)}</div></div>` : ""}
        </div>
      </div>
      <div>
        <div class="tb-tabs" role="tablist">
          <button type="button" role="tab" data-tab="work" aria-selected="true">Work<span class="n" id="d-bd-tabn"></span></button>
          <button type="button" role="tab" data-tab="comments" aria-selected="false">Comments${t.comments.length ? `<span class="n">${t.comments.length}</span>` : ""}</button>
          <button type="button" role="tab" data-tab="activity" aria-selected="false">Activity</button>
        </div>
        <div class="tb-pane" data-pane="work">
          <div class="progress" style="margin:0 0 12px"><i id="d-bd-bar" style="width:0%"></i></div>
          <div id="d-breakdown"></div>
          ${/* 🔴 APPLY A SERVICE TEMPLATE TO A CARD THAT ALREADY EXISTS (2026-08-14).
                Recipes could only be picked on the New Task form, so the commonest card on this
                board — a quick-added title, which is the RIGHT way to log work that comes up during
                the day (§3 of the task-placement guidelines) — could never be given a breakdown
                without retyping every phase. The catalog only served people who opened the full form.

                It lives at the BOTTOM of the Work pane, beside "Add main task", because that is
                where somebody is standing when they realise the card needs a plan. Hidden entirely
                for an Atrium card: its breakdown lives in Atrium's workspace JSON, and the route
                refuses one rather than half-working. */""}
          ${(readOnly || isAtrium) ? "" : `<div class="row" id="d-tpl-row" style="gap:8px;margin-top:10px;flex-wrap:wrap;align-items:center">
            <button class="btn sm ghost" id="d-bd-addmain">${S.ICON.plus}Add main task</button>
            <span class="tb-sep"></span>
            <select id="d-tpl" title="Fill this card's plan in from a service recipe">
              <option value="">Apply a service template…</option>
              ${templates.map((tp) => `<option value="${S.esc(tp.key)}">${S.esc(tp.dept)} — ${S.esc(tp.label)} (${tp.groups.length} phase${tp.groups.length === 1 ? "" : "s"})</option>`).join("")}
            </select>
          </div>`}
          ${(readOnly || !isAtrium) ? "" : `<button class="btn sm ghost" id="d-bd-addmain" style="margin-top:10px">${S.ICON.plus}Add main task</button>`}
        </div>
        <div class="tb-pane" data-pane="comments" hidden>
          ${(isAtrium && t.atrium_visible) ? `<div class="muted" style="font-size:12px;margin-bottom:10px">This card is shared, so the client sees these.</div>` : ""}
          <div class="thread" id="d-thread" style="margin:0 0 10px">${t.comments.map(cmt).join("") || '<div class="muted">No comments yet.</div>'}</div>
          ${readOnly ? "" : `<div class="row" style="gap:8px"><input id="d-comment" placeholder="Write a comment… use @name to mention"><button class="btn primary sm" id="d-send">Send</button></div>`}
        </div>
        <div class="tb-pane" data-pane="activity" hidden>
          <ul class="activity">${t.history.map((h) => `<li><span>${h.actor ? S.esc(h.actor.name) : "System"}</span> ${S.esc(h.field)} ${h.old_value ? `<span class="muted">${S.esc(h.old_value)} → </span>` : ""}<strong>${S.esc(h.new_value || "")}</strong> <span class="muted">· ${S.timeAgo(h.changed_at)}</span></li>`).join("") || '<li class="muted">Nothing yet.</li>'}</ul>
        </div>
      </div></div>`;
    // The bridge button means the opposite thing on each kind of card: a Sentinel row is PUSHED to
    // Atrium (one-way, client-safe fields only), while an Atrium card is already there — the toggle
    // just decides whether the client can see it.
    // No "Move to Review" shortcut — the For Review column was removed 2026-07-30 (statuses live in
    // task_vocab; a hardcoded status here would be a name the board no longer has a column for).
    // The lifecycle controls (Stage 2). All Sentinel-only: an Atrium-owned card has no local row to
    // hold a hold, a review or a filing, and faking one would split ownership of the record again.
    // Only the buttons that CAN act appear — the server enforces the same rules either way.
    //
    // 🔴 FINISHED WORK IS NOT PENDING WORK (2026-08-06). Park and Submit for review were offered on
    // EVERY unarchived card, including one sitting in a done column — so a delivered task showed
    // seven footer buttons, two of which mean nothing: parking work that is finished, and asking for
    // approval of a completion that already happened (the approval a review authorises is SPENT by
    // that completion — task_workflow.on_status_change). Neither is refused by the server, which is
    // precisely why they had to come out of the UI: they would both have "worked".
    // A card that comes back OUT of a done column gets both buttons again, because it is live work
    // again — the test is where the card is now, not what it once was.
    //
    // 🔴 PARK IS NOT A BUTTON ANY MORE (2026-08-06). Parking a card IS putting it in the parked
    // column, and the Move control below already does that — two controls for one state change is
    // the duplication the board's own "one field, ONE control" rule exists to prevent (see
    // frontend/README.md), and it was half of why this footer wrapped onto two rows. Nothing is
    // lost: choosing the parked stage in Move asks for the reason and calls the SAME `park`
    // endpoint, so `hold_reason` and `resume_to` are still written by `task_workflow`, never by a
    // bare status PATCH.
    //
    // Only the buttons this STATE offers stay inline; the rest go behind More.
    // START WORK / PAUSE (2026-09-02, services/task_sessions). The one running session is the
    // server's: `running` is true when it is on THIS card. Offered to whoever may edit the card and
    // only while the card is live work — not done, not filed, not parked (Resume comes first).
    const running = (t.sessions || []).find((s) => s.running && s.user_id === S.user.id);
    const mayWork = t.mine !== undefined ? (t.can_edit !== false) : true;
    // 🔴 Hidden entirely while ACTING AS someone — the server refuses time writes for them
    // (security.forbid_while_acting), and a button that can only 403 is the dead-button failure.
    const workBtn = (!isAtrium && !readOnly && !done && !t.archived && !isParked(t) && mayWork
        && !(S.user && S.user.acting_as))
      ? (running
        ? `<button class="btn ghost" id="d-pause">${S.ICON.clock}Pause</button><span class="tb-timer" id="d-timer" data-started="${S.esc(running.started_at)}"></span>`
        : `<button class="btn success" id="d-start">${S.ICON.check}Start Work</button>`)
      : "";
    const inlineActs = (isAtrium || readOnly) ? "" : [
      workBtn,
      // Resume shows while a hold is on, whatever column the card is in, or a card parked and then
      // dragged straight to done could never be un-parked.
      t.on_hold ? `<button class="btn ghost" id="d-resume">Resume</button>` : "",
      // Nothing to submit once it is approved, nothing to submit about filed work, and nothing to
      // submit about work that is already done.
      (!done && !t.archived && t.review_state !== "approved" && t.review_state !== "pending")
        ? `<button class="btn ghost" id="d-submit">Submit for review</button>` : "",
      (canReview(t) && t.review_state === "pending")
        ? `<button class="btn ghost" id="d-approve">Approve</button>
           <button class="btn ghost" id="d-changes">Request changes…</button>` : "",
    ].join("");
    // Behind More: rare, one-per-card or destructive. Every one of them keeps its id, so the wiring
    // below is unchanged — this is where the button sits, not what it does.
    const moreItems = [
      (isAtrium || readOnly) ? "" : filingBtn(t, done),
      // Send back (D11) — refuse queued work and return it to whoever filed it. Offered ONLY in the
      // exact state the rule allows: still unassigned, routed to a team, filed by somebody else, and
      // I am the one who could triage it. Once anyone owns it, reassigning is the honest move.
      (!isAtrium && !readOnly && canReview(t) && !t.assigned_to_id && t.assigned_team_id
        && t.created_by_id && t.created_by_id !== S.user.id)
        ? `<button class="btn ghost" id="d-sendback" title="Send this back to whoever filed it — it leaves your team's queue">Not ours…</button>` : "",
      canManage ? atriumControl(t, isAtrium) : "",
      (canManage && !isAtrium && t.atrium_sync_error) ? `<button class="btn ghost" id="d-atrium-retry">Retry the client push</button>` : "",
      canDelete(t) ? `<hr><button class="btn danger" id="d-delete">Delete this task</button>` : "",
    ].filter(Boolean);
    const more = moreItems.length
      ? `<details class="tb-more"><summary>More</summary><div class="tb-menu">${moreItems.join("")}</div></details>`
      : "";
    // 🔴 MOVING A CARD MUST NOT REQUIRE A MOUSE OR A CLOSED DIALOG. The board has three move
    // affordances (drag, the card's own select, the bulk bar) and the open record had NONE — you
    // closed the card to move the card. This is the same control the card carries (WP 5.5), in the
    // one place where the whole record is on screen to decide from.
    const moveCtl = readOnly ? ""
      : `<label class="tb-move"><span>Move to</span>
           <select id="d-move" aria-label="Move this task to another column">${moveOptions(t.status)}</select>
         </label>`;
    // The primary action, and the only status this dialog names: the DONE column, resolved by STAGE
    // (task_status_meta / D13) because every label here is renameable in Manage. A card already in a
    // done column has nothing to advance to. The review gate can still refuse it — 409
    // NEEDS_REVIEW — which the toast reports rather than the button pretending to be enabled.
    const doneStatus = STATUSES.find((s) => isDoneStatus(s));
    const advance = (!readOnly && !done && doneStatus)
      ? `<button class="btn primary" id="d-done">Mark complete</button>` : "";
    const footer = `${moveCtl}${readOnly ? "" : `<button class="btn ghost" id="d-edit">Edit</button>`}${inlineActs}${more}
      ${/* The two ways OUT stay together and stay right — as ONE flex item, so a footer forced to
            wrap on a narrow window can never leave the primary action stranded alone on a line of
            its own, which a bare spacer did. */""}
      <span class="tb-end"><button class="btn ${advance ? "ghost" : "primary"}" id="d-close">Close</button>${advance}</span>`;
    // The head is a KICKER, not a title: which client, which card, and whether it is published.
    // The task's own name is the h2 the body opens with.
    const kicker = [
      t.client_name || "Internal",
      isAtrium ? "Client card" : "Task " + t.id,
      (isAtrium ? t.atrium_visible : t.atrium_shared) ? "shared with the client" : "",
    ].filter(Boolean).join(" · ");
    const m = openTaskModal(kicker, body, footer, id);
    // Scoped to this dialog: `.tb-detail` restyles the head into that kicker, and every wide modal
    // on this board (the task form, Past work, the request queue) must keep its ordinary title.
    const modalEl = m.root.querySelector(".modal");
    if (modalEl) modalEl.classList.add("tb-detail");
    S.qs("#d-close").onclick = m.close;

    // Tabs: visibility only (see the body comment). `hidden` is honoured because `.tb-pane` sets no
    // display of its own — the trap documented at the top of styles.css.
    S.qsa(".tb-tabs button", m.root).forEach((b) => b.onclick = () => {
      S.qsa(".tb-tabs button", m.root).forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      S.qsa(".tb-pane", m.root).forEach((p) => { p.hidden = p.dataset.pane !== b.dataset.tab; });
    });

    // Move + Mark complete both go through ONE path, and it is the same PATCH the board's other
    // three move affordances use. Reopening the card afterwards is deliberate: the notice, the
    // facts strip and half the footer buttons all depend on the stage it just entered.
    //
    // 🔴 EXCEPT INTO THE PARKED COLUMN, which asks WHY first and posts `park` instead. A bare status
    // PATCH would land the card there with `hold_reason` and `resume_to` derived by `_sync_hold`
    // and no reason recorded at all — the card would say "Parked." with nothing after it, and
    // Resume would have no remembered column to name. This is what lets Park stop being a second
    // button for a state the column control already owns.
    const moveTo = async (to, sel) => {
      if (to === t.status) return;
      const reset = () => { if (sel) sel.value = t.status; };
      if (!isAtrium && STAGE_OF[to] === "blocked") {
        return askPark({
          hint: `It moves to the ${S.esc(to)} column and comes back to <strong>${S.esc(t.status)}</strong> when you resume it.`,
          onCancel: reset,
          onSubmit: (body) => act("park", body, "Parked"),
        });
      }
      try {
        await S.api(`/api/tasks/${id}/status`, { method: "PATCH", body: { status: to } });
        S.toast(`Moved to ${to}`, "ok");
        m.close(); load(); openDetail(id);
      } catch (err) {
        reset();                    // the card did not move; the control must not claim it did
        S.toast(err.detail || "Couldn't move that", "err");
      }
    };
    if (S.qs("#d-move")) {
      const sel = S.qs("#d-move");
      sel.onchange = () => moveTo(sel.value, sel);
    }
    if (S.qs("#d-done")) S.qs("#d-done").onclick = () => moveTo(doneStatus, S.qs("#d-move"));
    // Support is edited in the task form (which is where the field's own permission rules live).
    if (S.qs("#d-add-support")) S.qs("#d-add-support").onclick = () => { m.close(); taskForm(t); };
    if (S.qs("#d-atrium-retry")) S.qs("#d-atrium-retry").onclick = async () => {
      try {
        await S.api(`/api/tasks/${id}/atrium-retry`, { method: "POST" });
        S.toast("Sent — the client's card is current again", "ok");
        m.close(); load();
      } catch (err) { S.toast(err.detail || "Couldn't reach Atrium", "err"); }
    };

    // ---- Two-level work breakdown (main tasks -> sub-tasks, each optionally assigned) ----
    const mById = (mid) => t.maintasks.find((m) => m.id === mid);
    const sById = (m, sid) => (m ? m.subs.find((s) => s.id === sid) : null);
    // Strip the resolved-assignee objects back to the storable shape the API expects.
    const storable = () => t.maintasks.map((m) => ({
      id: m.id, title: m.title, assignee_id: m.assignee_id,
      subs: m.subs.map((s) => ({ id: s.id, text: s.text, done: s.done, assignee_id: s.assignee_id })),
    }));

    // `owners` is Sentinel's people list, or Atrium's roster on an Atrium card — same widget, one
    // vocabulary each, so the ids that go back are always the ones that system understands.
    //
    // D12 (WP 4.2g): the ROUTED TEAM'S people come first, and everyone else stays reachable below.
    // Work is routed to a department and then owned by someone in it, so that team is the answer
    // ~90% of the time — but "Justine, or anyone in the company" is a real need too, and a picker
    // that only listed one team would send people back to the Edit form to re-route first.
    // Two <optgroup>s rather than a filter, so the common case is at the top without hiding
    // anything. An Atrium roster carries no team, so it degrades to one flat list on its own.
    const optionFor = (p, current) =>
      `<option value="${S.esc(p.id)}" ${p.id === current ? "selected" : ""}>${S.esc(p.name)}</option>`;
    const ownerName = (oid) => {
      const p = owners.find((x) => x.id === oid);
      return p ? p.name : "Somebody else";
    };
    // 🔴 Both of these mirror the server, which is where they are enforced (routers/tasks.py: the
    // per-slot owner diff + task_perms.can_tick_step). Without them the drawer offered every step to
    // everyone and answered with a 403 that ALSO threw away the rest of the edit — the breakdown
    // saves whole.
    // Delegating an owner: AM+ anywhere, a team lead on their own department's card. Self-assignment
    // (taking an unowned step, dropping your own) stays open to every role, which is why a
    // non-delegator still gets a picker — it just only lists them.
    // An ATRIUM-owned card is unchanged: its owners are roster emails, not Sentinel users, so no
    // ownership rule can apply to them and `can_edit_atrium` (team lead and up) governs its content
    // wholesale. Narrowing that here would take an ability team leads have today.
    const mayDelegateStep = isAtrium ? !readOnly : canReassign(t);
    // Ticking: the step's owner, the card's lead, or a lead/manager. An unowned step is anyone's to
    // tick (that is how a team queue gets worked through). Atrium cards have no Sentinel owners at
    // all — their roster is emails — so they keep the old open behaviour.
    const mayTick = (owner) => isAtrium || !owner || owner === S.user.id
      || t.assigned_to_id === S.user.id || canReassign(t);

    function ownerOptions(current) {
      // A non-delegator may only ever write their own id, so listing the company is a promise the
      // server will refuse. They keep sight of who holds it via the disabled select's own value.
      if (!mayDelegateStep) {
        return owners.filter((p) => p.id === S.user.id || p.id === current)
          .map((p) => optionFor(p, current)).join("");
      }
      const teamId = t.assigned_team_id;
      const teamName = teamsById[teamId] ? teamsById[teamId].name : null;
      const inTeam = teamId ? owners.filter((p) => p.team_id === teamId) : [];
      if (!inTeam.length) return owners.map((p) => optionFor(p, current)).join("");
      const rest = owners.filter((p) => p.team_id !== teamId);
      return `<optgroup label="${S.esc(teamName || "This department")}">${inTeam.map((p) => optionFor(p, current)).join("")}</optgroup>`
        + (rest.length ? `<optgroup label="Everyone else">${rest.map((p) => optionFor(p, current)).join("")}</optgroup>` : "");
    }

    const assigneeSelect = (act, mid, sid, current, placeholder) => {
      // Somebody else's slot is shown, never editable: taking work off a colleague is the same power
      // as giving it to them, and the server refuses both.
      const locked = !mayDelegateStep && !!current && current !== S.user.id;
      const title = locked
        ? `${ownerName(current)} owns this — only a team lead or manager can change that`
        : (mayDelegateStep ? "" : "You can take this on yourself, or hand it back");
      return `<select class="bd-assignee" data-act="${act}" data-mid="${mid}"${sid ? ` data-sid="${sid}"` : ""}
        ${locked ? "disabled" : ""} title="${S.esc(title)}">
        <option value="">${placeholder}</option>
        ${ownerOptions(current)}
      </select>`;
    };

    // D12: assignment and routing are CONTROLS, not action buttons. The prototype had hardcoded
    // "Route to Acquisition" / "Delegate to Justine & Zhen" buttons, which only ever fit the one
    // example they were drawn for. These three controls are the general form of the same thing:
    // route the whole task, own a phase, own a step — plus one sweep for "the N nobody owns yet",
    // which is the actual daily action a lead takes after a service seeds twelve empty steps.
    function routingRow() {
      if (isAtrium || readOnly) return "";      // Atrium cards carry Atrium's own department field
      const unowned = t.maintasks.reduce(
        (n, m) => n + m.subs.filter((s) => !s.assignee_id).length, 0);
      const teamName = teamsById[t.assigned_team_id] ? teamsById[t.assigned_team_id].name : null;
      // "Department", not "Routed to": this select and the Edit form's Department field write the
      // SAME column (`assigned_team_id`), and calling it two different things in two places one
      // click apart made them read as two different settings that might disagree. One name.
      return `<div class="row bd-route" style="gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 10px">
        <span class="sub" style="font-size:12px">Department</span>
        <select id="bd-team" ${canReassign(t) ? "" : "disabled"} title="${canReassign(t) ? "Send this task to a department" : "Only a team lead or manager can re-route work"}">
          <option value="">Nobody yet</option>
          ${teams.map((tm) => `<option value="${tm.id}" ${tm.id === t.assigned_team_id ? "selected" : ""}>${S.esc(tm.name)}</option>`).join("")}
        </select>
        ${unowned ? `<select id="bd-bulkown" title="Give every step that nobody owns to one person">
          <option value="">Assign the ${unowned} unowned step${unowned > 1 ? "s" : ""} to…</option>
          ${ownerOptions(null)}
        </select>` : `<span class="sub" style="font-size:12px">${teamName ? "Every step has an owner" : ""}</span>`}
      </div>`;
    }

    function renderBreakdown() {
      let d = 0, total = 0;
      t.maintasks.forEach((m) => m.subs.forEach((s) => { total += 1; if (s.done) d += 1; }));
      // Three places show this count and ONE function derives it: the Progress fact, the Work
      // tab's own badge, and the bar. Ticking a step in a hidden pane still has to move the number
      // the reader is looking at, which is why the fact is written from here and not built inline.
      const fact = S.qs("#d-bd-count");
      if (fact) fact.textContent = total ? `${d} of ${total} steps` : "No breakdown";
      const tabn = S.qs("#d-bd-tabn");
      if (tabn) tabn.textContent = total ? `${d}/${total}` : "";
      S.qs("#d-bd-bar").style.width = (total ? Math.round(100 * d / total) : 0) + "%";
      S.qs("#d-breakdown").innerHTML = routingRow() + t.maintasks.map((m) => `
        <div class="mtask" data-mid="${m.id}">
          <div class="mtask-head">
            <input class="mtask-title" data-act="mt-title" data-mid="${m.id}" value="${S.esc(m.title)}" aria-label="Main task title">
            ${assigneeSelect("mt-assignee", m.id, null, m.assignee_id, "Owner…")}
            <button class="bd-x" data-act="mt-del" data-mid="${m.id}" title="Delete main task">✕</button>
          </div>
          <ul class="mtask-subs">${m.subs.map((s) => `
            <li class="${s.done ? "done" : ""}" data-sid="${s.id}">
              <input type="checkbox" data-act="sub-toggle" data-mid="${m.id}" data-sid="${s.id}" ${s.done ? "checked" : ""}
                ${mayTick(s.assignee_id) ? "" : `disabled title="${S.esc(ownerName(s.assignee_id) + " owns this step — only they or a lead can tick it")}"`}>
              <input class="sub-text" data-act="sub-text" data-mid="${m.id}" data-sid="${s.id}" value="${S.esc(s.text)}" aria-label="Sub-task">
              ${assigneeSelect("sub-assignee", m.id, s.id, s.assignee_id, "Assign…")}
              <button class="bd-x" data-act="sub-del" data-mid="${m.id}" data-sid="${s.id}" title="Delete sub-task">✕</button>
            </li>`).join("")}</ul>
          <div class="mtask-addsub">
            <input placeholder="Add a sub-task, then Enter…" data-act="sub-add-input" data-mid="${m.id}" aria-label="New sub-task">
          </div>
        </div>`).join("") || '<div class="muted" style="padding:4px 0">No breakdown yet. Add a main task to start.</div>';
      wireBreakdown();
    }

    // Persist the whole breakdown; refresh from the server response (gets ids for new items),
    // and roll back to a snapshot if the save fails.
    let saving = false;
    async function commit() {
      if (saving) return;
      saving = true;
      const snapshot = JSON.parse(JSON.stringify(t.maintasks));
      try {
        const updated = await S.api("/api/tasks/" + id, { method: "PATCH", body: { maintasks: storable() } });
        t.maintasks = Array.isArray(updated.maintasks) ? updated.maintasks : [];
        renderBreakdown();
      } catch (err) {
        t.maintasks = snapshot;
        renderBreakdown();
        S.toast(err.detail || "Couldn't save the breakdown", "err");
      } finally { saving = false; }
    }

    function wireBreakdown() {
      const q = (act) => S.qsa(`#d-breakdown [data-act="${act}"]`);
      // A viewer's breakdown is inert: disable the controls rather than let them look editable and
      // then 403 on blur. (The server refuses either way — this is about not lying to the user.)
      if (readOnly) {
        S.qsa("#d-breakdown input, #d-breakdown select, #d-breakdown button")
          .forEach((el) => { el.disabled = true; });
        return;
      }
      // D12 routing + bulk owner sweep. Both live outside the [data-act] grid because they act on
      // the TASK, not on one row of the breakdown.
      const teamSel = S.qs("#bd-team");
      if (teamSel && !teamSel.disabled) {
        teamSel.onchange = async () => {
          const value = teamSel.value ? Number(teamSel.value) : null;
          try {
            await S.api("/api/tasks/" + id, { method: "PATCH", body: { assigned_team_id: value } });
            t.assigned_team_id = value;
            // Re-routing changes the derived label (D14) AND which people head the owner pickers,
            // so the board and this drawer both need the new answer.
            S.toast(value ? "Routed to " + teamsById[value].name : "Routing cleared", "ok");
            renderBreakdown();
            load();
          } catch (err) {
            teamSel.value = t.assigned_team_id || "";
            S.toast(err.detail || "Couldn't re-route this task", "err");
          }
        };
      }
      const bulkOwn = S.qs("#bd-bulkown");
      if (bulkOwn) {
        bulkOwn.onchange = () => {
          const who = ownerId(bulkOwn.value);
          if (who === null) return;
          // Only the steps nobody owns. Never reassigns work that already has an owner — that is
          // someone's job, and a sweep is not the place to take it off them.
          t.maintasks.forEach((m) => m.subs.forEach((s) => { if (!s.assignee_id) s.assignee_id = who; }));
          commit();
        };
      }
      q("mt-title").forEach((el) => el.onchange = () => { const m = mById(el.dataset.mid); if (m) { m.title = el.value.trim() || "Untitled"; commit(); } });
      q("mt-assignee").forEach((el) => el.onchange = () => { const m = mById(el.dataset.mid); if (m) { m.assignee_id = ownerId(el.value); commit(); } });
      q("mt-del").forEach((el) => el.onclick = () => { t.maintasks = t.maintasks.filter((m) => m.id !== el.dataset.mid); commit(); });
      q("sub-toggle").forEach((el) => el.onchange = () => { const s = sById(mById(el.dataset.mid), el.dataset.sid); if (s) { s.done = el.checked; commit(); } });
      q("sub-text").forEach((el) => el.onchange = () => { const s = sById(mById(el.dataset.mid), el.dataset.sid); if (s) { s.text = el.value.trim(); commit(); } });
      q("sub-assignee").forEach((el) => el.onchange = () => { const s = sById(mById(el.dataset.mid), el.dataset.sid); if (s) { s.assignee_id = ownerId(el.value); commit(); } });
      q("sub-del").forEach((el) => el.onclick = () => { const m = mById(el.dataset.mid); if (m) { m.subs = m.subs.filter((s) => s.id !== el.dataset.sid); commit(); } });
      q("sub-add-input").forEach((el) => el.onkeydown = (e) => {
        if (e.key !== "Enter") return;
        const m = mById(el.dataset.mid); const text = el.value.trim();
        // The placeholder id is replaced by a real one on save (both systems mint their own).
        if (m && text) { m.subs.push({ id: "st_new_" + Date.now(), text, done: false, assignee_id: ownerId("") }); commit(); }
      });
    }

    if (S.qs("#d-bd-addmain")) S.qs("#d-bd-addmain").onclick = () => {
      t.maintasks.push({ id: "mt_new_" + Date.now(), title: "New main task", assignee_id: null, subs: [] });
      commit();
    };
    // Apply a service template to THIS card. 🔴 The mode is decided here and sent explicitly — the
    // server refuses to guess (schemas.TaskApplyTemplateIn), because `replace` discards every tick
    // and every step owner already on the card and that is not recoverable. An empty breakdown has
    // nothing to lose, so it skips the question entirely rather than asking a pointless one.
    const tplSel = S.qs("#d-tpl");
    async function applyTemplate(key, mode) {
      try {
        const updated = await S.api(`/api/tasks/${id}/apply-template`,
                                    { method: "POST", body: { service_key: key, mode } });
        t.maintasks = Array.isArray(updated.maintasks) ? updated.maintasks : [];
        renderBreakdown();
        S.toast(mode === "replace" ? "Plan replaced from the service template"
                                   : "Service template added to the plan", "ok");
        load();
      } catch (err) { S.toast(err.detail || "Couldn't apply that service template", "err"); }
    }
    if (tplSel) tplSel.onchange = () => {
      const key = tplSel.value;
      tplSel.value = "";                       // an action menu, not a stored value
      if (!key) return;
      const tpl = templates.find((x) => x.key === key);
      // An empty breakdown has nothing to lose, so it skips the question rather than asking a
      // pointless one. `append` and `replace` are identical in that case.
      if (!t.maintasks.length) { applyTemplate(key, "append"); return; }
      // 🔴 Otherwise the mode is a real choice and the user makes it. `replace` discards every tick
      // and every step owner on the card, which nothing can undo — so the count of what is about to
      // be lost is named, not implied. The server refuses to default this for the same reason.
      const steps = tpl ? tpl.groups.reduce((n, g) => n + g.subs.length, 0) : 0;
      const done = t.maintasks.reduce((n, m) => n + m.subs.filter((s) => s.done).length, 0);
      const cm = S.modal({
        title: "This card already has a plan",
        body: `<p style="line-height:1.5">Add <strong>${S.esc(tpl ? tpl.label : key)}</strong>’s
             ${tpl ? tpl.groups.length : 0} phase(s) and ${steps} step(s) to the
             ${t.maintasks.length} already on this card, or start over from the recipe?<br>
             <span class="muted">Starting over deletes the current breakdown${
               done ? ` — including <strong>${done} step${done === 1 ? "" : "s"} already ticked</strong>` : ""},
             and any owners named on it. This can't be undone.</span></p>`,
        footer: `<button class="btn ghost" id="tpl-cancel">Cancel</button>
                 <button class="btn danger" id="tpl-replace">Start over</button>
                 <button class="btn primary" id="tpl-append">Add to the plan</button>`,
      });
      S.qs("#tpl-cancel").onclick = cm.close;
      S.qs("#tpl-append").onclick = () => { cm.close(); applyTemplate(key, "append"); };
      S.qs("#tpl-replace").onclick = () => { cm.close(); applyTemplate(key, "replace"); };
    };
    renderBreakdown();
    // Comment
    if (S.qs("#d-send")) S.qs("#d-send").onclick = async () => {
      const val = S.qs("#d-comment").value.trim(); if (!val) return;
      try {
        const c = await S.api(`/api/tasks/${id}/comments`, { method: "POST", body: { body: val } });
        const thr = S.qs("#d-thread"); if (thr.querySelector(".muted")) thr.innerHTML = "";
        thr.insertAdjacentHTML("beforeend", cmt(c)); S.qs("#d-comment").value = "";
      } catch (err) { S.toast(err.detail || "Couldn't post that comment", "err"); }
    };
    // A client's "Request changes" (Atrium cards only — clients raise them on their Progress tab).
    // Clearing one is a team action, so it belongs wherever the team is working: here too.
    // Clears the TASK-level client-changes flag (D4). Separate from wireResolve below, which
    // resolves ONE Atrium comment — a Sentinel row has no per-comment resolve, only this counter.
    // The endpoint is idempotent, so two people clicking it is a race nobody loses.
    const resolveBtn = S.qs("#d-resolve-changes");
    if (resolveBtn) resolveBtn.onclick = async () => {
      resolveBtn.disabled = true;
      try {
        await S.api(`/api/tasks/${id}/resolve-client-changes`, { method: "POST" });
        S.toast("Marked as handled", "ok");
        m.close(); load(); openDetail(id);
      } catch (err) { resolveBtn.disabled = false; S.toast(err.detail || "Couldn't clear that", "err"); }
    };
    wireResolve();
    function wireResolve() {
      S.qsa("[data-resolve]").forEach((b) => b.onclick = async () => {
        b.disabled = true;
        try {
          await S.api(`/api/tasks/${id}/comments/${b.dataset.resolve}/resolve`, { method: "POST" });
          S.toast("Change request resolved", "ok");
          m.close(); load(); openDetail(id);
        } catch (err) { b.disabled = false; S.toast(err.detail || "Couldn't resolve that", "err"); }
      });
    }
    // Priority (AM only)
    if (S.qs("#d-priority")) S.qs("#d-priority").onchange = async (e) => {
      try { await S.api(`/api/tasks/${id}/priority`, { method: "PATCH", body: { priority: e.target.value } }); S.toast("Priority updated", "ok"); }
      catch (err) { S.toast(err.detail, "err"); }
    };
    if (S.qs("#d-atrium")) S.qs("#d-atrium").onclick = async () => {
      try {
        if (isAtrium) {
          // Already in Atrium — this only flips whether the client sees it on their Progress tab.
          await S.api(`/api/tasks/${id}`, { method: "PATCH", body: { atrium_visible: !t.atrium_visible } });
          S.toast(t.atrium_visible ? "Hidden from the client" : "Shared with the client", "ok");
        } else {
          await S.api(`/api/tasks/${id}/send-to-atrium`, { method: "POST" });
          S.toast("Client-safe fields sent to Atrium", "ok");
        }
        m.close(); load();
      } catch (err) { S.toast(err.detail, "err"); }
    };
    // ---- Lifecycle: park / resume / file / review (Stage 2) ----
    // One helper: POST, tell the user what happened, then reopen the drawer so every chip, field
    // and button reflects the new state (the buttons themselves depend on it).
    const act = async (path, body, msg) => {
      try {
        await S.api(`/api/tasks/${id}/${path}`, { method: "POST", body });
        S.toast(msg, "ok");
        m.close(); load(); openDetail(id);
      } catch (err) { S.toast(err.detail || "Couldn't do that", "err"); }
    };
    // Park has no button of its own — it is what the Move control does when the target is the
    // parked stage (see moveTo above).
    if (S.qs("#d-resume")) S.qs("#d-resume").onclick = () =>
      act("resume", {}, "Back on the board");
    // Start Work / Pause (2026-09-02). Both re-read the topbar strip, and tell any Today page that
    // is listening (today.js) to re-read its time card.
    const afterSession = () => { if (S.refreshWorkStrip) S.refreshWorkStrip(); document.dispatchEvent(new CustomEvent("sentinel:session")); };
    if (S.qs("#d-start")) S.qs("#d-start").onclick = async () => {
      try {
        const r = await S.api(`/api/tasks/${id}/sessions/start`, { method: "POST" });
        S.toast(r.moved ? "Started — moved to In Progress" : "Started", "ok");
        afterSession(); m.close(); load(); openDetail(id);
      } catch (err) { S.toast(err.detail || "Couldn't start", "err"); }
    };
    if (S.qs("#d-pause")) S.qs("#d-pause").onclick = async () => {
      try {
        await S.api(`/api/tasks/${id}/sessions/pause`, { method: "POST" });
        S.toast("Paused — the time is saved on the card", "ok");
        afterSession(); m.close(); load(); openDetail(id);
      } catch (err) { S.toast(err.detail || "Couldn't pause", "err"); }
    };
    const timerEl = S.qs("#d-timer", m.root);
    if (timerEl) {
      const started = Date.parse(timerEl.dataset.started);
      const tick = () => {
        if (!document.body.contains(timerEl)) { clearInterval(iv); return; }
        const s = Math.max(0, Math.floor((Date.now() - started) / 1000));
        timerEl.textContent = (s >= 3600 ? Math.floor(s / 3600) + ":" : "") + String(Math.floor((s % 3600) / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
      };
      tick();
      const iv = setInterval(tick, 1000);
    }
    if (S.qs("#d-submit")) S.qs("#d-submit").onclick = () =>
      act("review/submit", {}, "Sent for review — your lead has been notified");
    if (S.qs("#d-approve")) S.qs("#d-approve").onclick = () =>
      act("review/approve", {}, "Approved — it can be completed now");
    if (S.qs("#d-changes")) S.qs("#d-changes").onclick = () => askReason({
      title: "Request changes",
      hint: "The card moves back to the revision column and whoever holds it is notified.",
      label: "What needs changing?",
      confirm: "Request changes",
      onSubmit: (note) => act("review/request-changes", { note }, "Sent back with your note"),
    });
    if (S.qs("#d-archive")) S.qs("#d-archive").onclick = () =>
      act("archive", {}, "Filed to Past work");
    if (S.qs("#d-sendback")) S.qs("#d-sendback").onclick = () => askReason({
      title: "Send this back?",
      hint: `It leaves your team's queue and goes back to <strong>${S.esc((t.created_by && t.created_by.name) || "whoever filed it")}</strong>, assigned to them.
             You will not see it here afterwards — that is the point.`,
      label: "Why isn't this yours? (internal — the client never sees it)",
      confirm: "Send it back",
      onSubmit: (reason) => act("send-back", { reason }, "Sent back"),
    });
    if (S.qs("#d-unarchive")) S.qs("#d-unarchive").onclick = () =>
      act("unarchive", {}, "Back on the board");

    if (S.qs("#d-edit")) S.qs("#d-edit").onclick = () => { m.close(); taskForm(t); };
    if (S.qs("#d-delete")) S.qs("#d-delete").onclick = () => confirmDelete(t, m);
  }

  // (`pausedColumn()` lived here until 2026-08-06. Park lost its button — the Move control owns
  // that column now — and the one place that still has to recognise the parked column asks
  // `STAGE_OF[target] === "blocked"` directly. The rule it carried is unchanged and still absolute:
  // recognise the column by its STAGE, never by the literal "Blocked", which Manage can rename.)

  // A small "why?" prompt, shared by Park, Request changes, Send back and Decline. All four write
  // prose that has to be recorded, and all four are refusals of a sort, so they ask the same way.
  // `require: true` for the one whose text a CLIENT reads — an empty decline reason is the thing the
  // reverse channel exists to prevent. The other three allow a blank: parking work you will explain
  // in person is real, and forcing a sentence there only teaches people to type ".".
  //
  // Since 2026-08-06 this opens ON TOP of the card rather than replacing it (S.modal stacks), so
  // Cancel returns you to the task you were reading instead of closing it.
  // `onCancel` fires on EVERY way out that is not the confirm button — Cancel, ✕, Esc, backdrop —
  // which is what a caller needs when the prompt was opened BY a control that has already changed
  // (the record's Move select): abandoning the prompt has to put that control back.
  // Park asks WHY in two halves (2026-09-02): a structured kind (constants.HOLD_KINDS — what the AM's
  // and COO's "waiting on the client vs waiting on us" split counts) and one line of prose. Both are
  // internal; the client sees the stage and nothing else. `kind` defaults to "client" because that is
  // the commonest reason work stops, and a wrong default is visible in the chips rather than silent.
  const HOLD_KINDS = {
    client: "Waiting on client", access: "Waiting for access", asset: "Waiting for an asset",
    am_decision: "Waiting for AM decision", reviewer: "Waiting for reviewer",
    task: "Waiting on another task", other: "Other",
  };
  function askPark({ hint, onSubmit, onCancel }) {
    let submitted = false, kind = "client";
    const rm = S.modal({
      onClose: () => { if (!submitted && onCancel) onCancel(); },
      title: "Park this task?",
      body: `<div class="stack" style="gap:12px">
        <div class="form-hint">${hint}</div>
        <label class="field"><span>Why is it waiting? (internal — the client never sees this)</span>
          <div class="hold-kinds" id="pk-kinds">${Object.entries(HOLD_KINDS).map(([k, v]) =>
            `<button type="button" class="choice ${k === kind ? "on" : ""}" data-k="${k}">${S.esc(v)}</button>`).join("")}</div></label>
        <label class="field"><span>One line for whoever picks this up</span><textarea id="pk-text" rows="2" placeholder="Who or what is it on?"></textarea></label>
      </div>`,
      footer: `<button class="btn ghost" id="pk-cancel">Cancel</button><button class="btn primary" id="pk-ok">Park it</button>`,
    });
    S.qs("#pk-cancel", rm.root).onclick = rm.close;
    S.qsa("#pk-kinds .choice", rm.root).forEach((b) => b.onclick = () => {
      kind = b.dataset.k;
      S.qsa("#pk-kinds .choice", rm.root).forEach((x) => x.classList.toggle("on", x === b));
    });
    S.qs("#pk-ok", rm.root).onclick = () => {
      submitted = true;
      rm.close();
      onSubmit({ reason: S.qs("#pk-text", rm.root).value.trim(), kind });
    };
  }

  function askReason({ title, hint, label, confirm, require: needsText, onSubmit, onCancel }) {
    let submitted = false;
    const rm = S.modal({
      onClose: () => { if (!submitted && onCancel) onCancel(); },
      title,
      body: `<div class="stack" style="gap:12px">
        <div class="form-hint">${hint}</div>
        <label class="field"><span>${label}</span><textarea id="rz-text" rows="3"></textarea></label>
      </div>`,
      footer: `<button class="btn ghost" id="rz-cancel">Cancel</button><button class="btn primary" id="rz-ok">${S.esc(confirm)}</button>`,
    });
    S.qs("#rz-cancel").onclick = rm.close;
    const box = S.qs("#rz-text", rm.root);
    box.focus();
    S.qs("#rz-ok", rm.root).onclick = () => {
      const text = box.value.trim();
      if (needsText && !text) { S.toast("A reason is required here", "err"); return; }
      submitted = true;             // set BEFORE close, or onClose reports this as a cancel
      rm.close();
      onSubmit(text);
    };
  }

  // Past work: the filed tasks, out of the way but never lost (M4). A separate fetch rather than a
  // filter on the board's list — `?archived=1` returns filed rows ONLY, and the two never mix.
  async function showPastWork() {
    const pm = S.modal({
      title: "Past work",
      drawer: true,
      body: `<div class="skeleton-row">Loading…</div>`,
      footer: `<button class="btn primary" id="pw-close">Close</button>`,
    });
    S.qs("#pw-close").onclick = pm.close;
    // Scoped to OUR overlay. This used to take the last `.overlay.drawer-ov .modal-body` in the
    // document, on the theory that a task drawer might be open behind it — which was guesswork about
    // DOM order back when every modal shared one element. `S.modal` returns its own root now, so ask
    // it directly and the answer can't be another dialog's body.
    const box = pm.root.querySelector(".modal-body");
    let rows;
    try { rows = await S.api("/api/tasks?archived=1"); }
    catch (err) { box.innerHTML = `<div class="empty">${S.esc(err.detail || "Couldn't load past work.")}</div>`; return; }
    if (!rows.length) {
      box.innerHTML = `<div class="empty">Nothing filed yet. Completed work gets filed here so the
        board's Completed column stays a working column, not a graveyard.</div>`;
      return;
    }
    box.innerHTML = `<div class="lead" style="margin-bottom:12px">${rows.length} filed task${rows.length > 1 ? "s" : ""}.
        Filing is internal — a client's card stays exactly where it is.</div>
      <table class="mon-tbl"><thead><tr><th>Task</th><th>Client</th><th>Completed</th><th></th></tr></thead>
      <tbody>${rows.map((r) => `<tr data-id="${r.id}">
        <td><div class="n">${S.esc(r.title)}</div><div class="r muted">${S.esc(r.status)}</div></td>
        <td>${S.esc(r.client_name || "—")}</td>
        <td>${r.completed_at ? S.fmtDate(r.completed_at) : '<span class="muted">—</span>'}</td>
        <td><button class="btn sm ghost" data-restore="${r.id}">Restore</button></td>
      </tr>`).join("")}</tbody></table>`;
    S.qsa("[data-restore]").forEach((b) => b.onclick = async (e) => {
      e.stopPropagation();
      b.disabled = true;
      try {
        await S.api(`/api/tasks/${b.dataset.restore}/unarchive`, { method: "POST" });
        S.toast("Back on the board", "ok"); pm.close(); load();
      } catch (err) { b.disabled = false; S.toast(err.detail || "Couldn't restore that", "err"); }
    });
    S.qsa(".mon-tbl tbody tr").forEach((tr) => tr.onclick = () => { pm.close(); openDetail(tr.dataset.id); });
  }

  // "Filed by me" (§2.4d, decision D10): work you raised that is now somebody else's. It is NOT
  // on your board -- routing a card to another team takes it off yours, deliberately -- so this
  // answers the one question that leaves behind: where did it go? Team, current owner or "awaiting
  // triage", and whether it was sent back. No internal fields: it may be another department's now.
  async function showFiledByMe() {
    const fm = S.modal({
      title: "Filed by me",
      drawer: true,
      body: `<div class="skeleton-row">Loading…</div>`,
      footer: `<button class="btn primary" id="fm-close">Close</button>`,
    });
    S.qs("#fm-close").onclick = fm.close;
    const box = fm.root.querySelector(".modal-body");     // scoped, as in showPastWork
    let rows;
    try { rows = await S.api("/api/tasks/filed-by-me"); }
    catch (err) { box.innerHTML = `<div class="empty">${S.esc(err.detail || "Couldn't load that list.")}</div>`; return; }
    if (!rows.length) {
      box.innerHTML = `<div class="empty">Nothing here. Work you raise and keep stays on your board;
        this list is for what you routed to another team.</div>`;
      return;
    }
    const where = (r) => {
      if (r.sent_back_reason) return `<span class="pill red">Sent back</span> <span class="muted">${S.esc(r.sent_back_reason)}</span>`;
      if (r.awaiting_triage) return `<span class="pill amber">Awaiting triage</span> <span class="muted">in ${S.esc(r.team_name || "a team")}</span>`;
      if (r.owner_name) return `<span class="muted">with ${S.esc(r.owner_name)}${r.team_name ? " · " + S.esc(r.team_name) : ""}</span>`;
      return `<span class="muted">unrouted</span>`;
    };
    box.innerHTML = `<div class="lead" style="margin-bottom:12px">${rows.length} item${rows.length > 1 ? "s" : ""} you
        raised for someone else — where it went, not the internal detail, which is theirs now.</div>
      <div class="card">${rows.map((r) => `<div style="padding:12px 14px;border-bottom:1px solid var(--line-soft)">
        <div class="row" style="justify-content:space-between;gap:10px">
          <strong style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${S.esc(r.title)}</strong>
          <span class="sub" style="flex:none;font-size:12px">${S.esc(r.status)}${r.on_hold ? " · ⏸" : ""}</span>
        </div>
        <div style="margin-top:5px;font-size:12.5px">${where(r)}${r.client_name
          ? `<span class="muted"> · ${S.esc(r.client_name)}</span>` : ""}</div>
      </div>`).join("")}</div>`;
  }

  // Confirm-then-delete. A Sentinel row is gone for good (no bin); an Atrium card soft-deletes into
  // Atrium's own Bin, so say so rather than warning about something irreversible that isn't.
  function confirmDelete(t, parent) {
    const cm = S.modal({
      title: t.source === "atrium" ? "Delete this client card?" : "Delete task?",
      body: `<p style="line-height:1.5">Delete <strong>${S.esc(t.title)}</strong>?<br>
        <span class="muted">${t.source === "atrium"
          ? "It leaves this board and the client's Progress tab, and goes to Atrium's Bin — restorable there for 30 days."
          : "This also removes its checklist, comments, and activity. This can't be undone."}</span></p>`,
      footer: `<button class="btn ghost" id="cd-cancel">Cancel</button><button class="btn danger" id="cd-yes">Delete task</button>`,
    });
    S.qs("#cd-cancel").onclick = cm.close;
    S.qs("#cd-yes").onclick = async () => {
      S.qs("#cd-yes").disabled = true;
      try {
        await S.api("/api/tasks/" + t.id, { method: "DELETE" });
        S.toast("Task deleted", "ok"); cm.close(); if (parent) parent.close(); load();
      } catch (err) { S.qs("#cd-yes").disabled = false; S.toast(err.detail || "Couldn't delete the task", "err"); }
    };
  }

  // Atrium cards carry one comment kind Sentinel rows don't: a client's "Request changes", which
  // stays flagged until someone on the team clears it (see wireResolve in the drawer).
  // 🔴 `is_client` is finally read here. A client's words on an internal thread have to be
  // unmistakable — the reply is written differently depending on who is going to read it — and the
  // serializer has advertised this field for exactly that since D4 while nothing consumed it.
  // The `[atrium:<id>]` de-dupe marker is stripped: it rides in the body so the receiver needs no
  // extra column (see internal.internal_task_feedback), and it is plumbing, not something the
  // client typed.
  const cmt = (c) => `<div class="cmt">${S.avatar(c.author, "sm")}<div class="body">
      <strong>${S.esc(c.author ? c.author.name : "?")}</strong>${c.is_client
        ? `<span class="pill violet" style="margin-left:6px">Client</span>` : ""}${c.kind === "changes"
        ? `<span class="pill ${c.resolved ? "green" : "red"}" style="margin-left:6px">${c.resolved ? "Resolved" : "Changes requested"}</span>` : ""}
      <div>${S.esc(String(c.body || "").replace(/\n?\[atrium:[^\]]*\]/g, "").trim())}</div>
      <div class="meta">${S.timeAgo(c.created_at)}</div>
      ${(c.kind === "changes" && !c.resolved) ? `<button class="btn sm ghost" style="margin-top:6px" data-resolve="${S.esc(c.id)}">Mark resolved</button>` : ""}
    </div></div>`;

  // The Edit form for an Atrium-owned card. A SEPARATE form from taskForm on purpose: it edits
  // Atrium's own fields (its department vocabulary, roster owners as emails, launch + start dates,
  // the hold switch) and Sentinel's field names would either be ignored or mean something subtly
  // different. Both forms save through the same PATCH /api/tasks/{id}; the router routes by id, and
  // the bridge translates (services/atrium_tasks.FIELD_MAP).
  //
  // 🔴 TWO FIELDS WERE REMOVED FROM THIS FORM ON 2026-08-06, both because they were second copies
  // of a control that already exists one click away — and two controls over one value can display
  // opposite states in the same session:
  //   • Status — the board moves cards. Drag, the card's own move select and the bulk bar all go
  //     through `moveCard`/`/status`. This form had to send it as a SECOND request (in Atrium a
  //     status change is a stage MOVE with its own endpoint and its own history entry), so a failure
  //     there left every other field already saved and the card in its old column: a half-save with
  //     an error toast over it. There is now one way to move a card, and it cannot half-fail.
  //   • Client visibility — the footer's own "✓ Client can see this" toggle owns it (atriumControl).
  //     A checkbox here duplicated the one decision on this card that a client can actually see.
  function atriumTaskForm(t) {
    const depts = t.atrium_departments || [];
    const roster = t.atrium_roster || [];
    const support = t.atrium_support_ids || [];
    const extrasOpen = !!(t.atrium_department || t.atrium_lead_id || support.length || t.content_type
      || t.service_charge || t.deliverable_url || t.internal_notes || t.on_hold || campaignOf(t)
      || (t.priority && t.priority !== "Medium"));
    const m = S.modal({
      title: "Edit client card",
      wide: true,
      body: `<div class="grid" style="grid-template-columns:1fr 1fr;gap:16px">
        <div class="form-hint" style="grid-column:1/-1">This card lives in ${S.esc(t.client_name || "Atrium")}'s workspace — saving writes straight back to Atrium.</div>
        <label class="field" style="grid-column:1/-1"><span>Task name</span>
          <input id="a-title" value="${S.esc(t.title || "")}" placeholder="${S.esc(NAME_PLACEHOLDER)}">
          <div class="form-hint">${NAME_HINT}</div></label>
        <label class="field" style="grid-column:1/-1"><span>Client note — the client reads this</span><textarea id="a-cnote" rows="3" placeholder="Optional">${S.esc(t.client_facing_notes || "")}</textarea></label>
        <label class="field"><span>Launch date</span><input type="date" id="a-due" value="${t.due_date || ""}"></label>
        <label class="field"><span>Start date</span><input type="date" id="a-start" value="${t.start_date || ""}"></label>
        <div class="field" style="grid-column:1/-1">
          <details class="tk-extra"${extrasOpen ? " open" : ""}>
            <summary>More options${extrasOpen ? "" : " — department, lead, priority, hold…"}</summary>
            <div class="grid" style="grid-template-columns:1fr 1fr;gap:16px;margin-top:12px">
              <label class="field"><span>Department</span><select id="a-dept"><option value="">—</option>${depts.map((d) => `<option value="${S.esc(d.key)}" ${d.key === t.atrium_department ? "selected" : ""}>${S.esc(d.label)}</option>`).join("")}</select></label>
              <label class="field"><span>Lead</span><select id="a-lead"><option value="">Unassigned</option>${roster.map((p) => `<option value="${S.esc(p.id)}" ${p.id === t.atrium_lead_id ? "selected" : ""}>${S.esc(p.name)}</option>`).join("")}</select></label>
              <label class="field" style="grid-column:1/-1"><span>Support — pick as many as you need</span><select id="a-support" multiple size="4">${roster.map((p) => `<option value="${S.esc(p.id)}" ${support.indexOf(p.id) >= 0 ? "selected" : ""}>${S.esc(p.name)}</option>`).join("")}</select></label>
              ${isAM ? `<label class="field"><span>Priority</span><select id="a-priority">${vocab.priorities.map((p) => `<option ${p === (t.priority || "Medium") ? "selected" : ""}>${p}</option>`).join("")}</select></label>` : ""}
              <label class="field"><span>Content type</span><input id="a-ctype" value="${S.esc(t.content_type || "")}"></label>
              ${/* 🔴 Editable here since 2026-08-11, and it was a real gap rather than a deliberate
                    omission: `FIELD_MAP` has always mapped `campaign`, and this board's campaign
                    filter and search now read it on BOTH kinds of card — so a client card could be
                    grouped by a campaign nobody could set from the only surface that edits it.
                    Same datalist as the Sentinel form: the names come off this board, and a grouping
                    key retyped by hand is a second campaign. */""}
              <label class="field"><span>Campaign</span>
                <input id="a-campaign" value="${S.esc(t.campaign || "")}" placeholder="e.g. Stratos"
                  list="a-campaign-list" autocomplete="off">
                <datalist id="a-campaign-list">${campaignNames(allTasks)
                  .map((n) => `<option value="${S.esc(n)}"></option>`).join("")}</datalist></label>
              <label class="field"><span>Service charge ($)</span><input id="a-charge" inputmode="decimal" value="${S.esc(t.service_charge || "")}" placeholder="0" pattern="[0-9]*[.]?[0-9]*" title="Optional — numbers only (e.g. 4200 or 4200.50)"></label>
              <label class="field" style="grid-column:1/-1"><span>Deliverable URL (client-safe)</span><input id="a-deliv" value="${S.esc(t.deliverable_url || "")}"></label>
              <label class="field" style="grid-column:1/-1"><span>${S.ICON.lock}Internal notes</span><textarea id="a-inotes">${S.esc(t.internal_notes || "")}</textarea></label>
              <div class="field" style="grid-column:1/-1"><span>On hold</span>
                <label class="row" style="gap:8px;margin-top:6px"><input type="checkbox" id="a-hold" ${t.on_hold ? "checked" : ""}><span class="sub">Paused — the client only ever sees "Paused", never the reason</span></label></div>
              <label class="field" style="grid-column:1/-1"><span>${S.ICON.lock}Hold reason</span><input id="a-holdwhy" value="${S.esc(t.hold_reason || "")}" placeholder="Internal — why it's paused"></label>
            </div>
          </details>
        </div>`,
      footer: `<button class="btn ghost" id="a-cancel">Cancel</button><button class="btn primary" id="a-save">Save changes</button>`,
    });
    S.qs("#a-cancel").onclick = m.close;
    S.qs("#a-title").focus();

    S.qs("#a-save").onclick = async () => {
      const body = {
        title: S.qs("#a-title").value.trim() || "Untitled task",
        client_facing_notes: S.qs("#a-cnote").value,
        due_date: S.qs("#a-due").value || null,
        start_date: S.qs("#a-start").value || null,
        atrium_department: S.qs("#a-dept").value,
        atrium_lead_id: S.qs("#a-lead").value,
        atrium_support_ids: Array.from(S.qs("#a-support").options).filter((o) => o.selected).map((o) => o.value),
        content_type: S.qs("#a-ctype").value,
        // `null` when blank, not "" — `update_task` uses `exclude_unset`, so an explicit null is what
        // actually CLEARS a campaign; "" would store an empty string that every `if (campaign)` on
        // this board then treats as set-but-blank.
        campaign: S.qs("#a-campaign").value.trim() || null,
        service_charge: S.qs("#a-charge").value || null,
        deliverable_url: S.qs("#a-deliv").value,
        internal_notes: S.qs("#a-inotes").value,
        on_hold: S.qs("#a-hold").checked,
        hold_reason: S.qs("#a-holdwhy").value,
      };
      if (isAM) body.priority = S.qs("#a-priority").value;
      // ONE request. `atrium_visible` and `status` both used to be sent from here — see the note on
      // this function for why neither belongs in a form.
      const btn = S.qs("#a-save");
      btn.disabled = true;
      try {
        await S.api("/api/tasks/" + t.id, { method: "PATCH", body });
        S.toast("Card updated", "ok"); m.close(); load();
      } catch (err) { btn.disabled = false; S.toast(err.detail || "Couldn't save that card", "err"); }
    };
  }

  function taskForm(existing, presetStatus) {
    if (existing && existing.source === "atrium") return atriumTaskForm(existing);
    const e = existing || {};
    // 🔴 STATUS IS NOT A FORM FIELD (2026-08-06). The board MOVES cards — drag, the card's own move
    // select, the bulk bar's "Move to…" — and all three go through `moveCard`, which is optimistic,
    // undoable and rolls back on failure. A fourth way to set the same column, buried under More
    // options and saved with a batch of unrelated edits, had none of that and gave the field two
    // different save semantics one click apart. Where a NEW card lands is still a real choice, and
    // it is still made: the column's own "Add card" passes `presetStatus`, and the New Task button
    // means the first column. Editing a card no longer sends `status` at all.
    const newStatus = presetStatus || (STATUSES.length ? STATUSES[0] : "To Do");
    // Only spring the rare-fields block open when an EXISTING task already carries one of those
    // values -- otherwise editing would silently hide something the user themselves set. A new
    // task always starts collapsed.
    // 🔴 The list is SHORT now because the block is short now: client, department, lead, support,
    // priority, campaign and service type moved OUT of it onto visible rows (see the .tf-* styles),
    // so only the four rare fields and the origin correction are left to spring open. Adding a
    // field to this test that is no longer inside the block does nothing at all.
    const extrasOpen = !!existing && !!(e.service_charge || e.content_type || e.deliverable_url
      || e.internal_notes || e.origin);
    // 🔴 Campaign is a GROUPING field, not the name (§7 of docs/TASKBOARD_REBUILD.md, built
    // 2026-08-04). Until then ONE input wrote into both `title` and `campaign`, so the detail
    // modal's Campaign row just echoed the title back on every task. The name field is now the
    // name. Existing rows keep their duplicated value until someone edits them — `campaignOf` is
    // what stops that duplicate being displayed anywhere.
    //
    // 🔴 IT IS NOW OFFERED ON EVERY TASK, not only a campaign-shaped one (2026-08-11). It used to be
    // revealed by `content_type === "Campaign"` — i.e. by picking the one campaign service template —
    // and that made the field unreachable for exactly the cards that need it most. Per §4 of the
    // task-placement guidelines, work raised AFTER a campaign launches is deliberately a separate
    // one-line task with no service template and no campaign content type, so the field it needed to
    // fill was hidden by the very rule meant to keep the form tidy: campaign grouping could only ever
    // cover campaign-BUILD cards, which are the ones least in need of grouping (there is one).
    // It lives inside More options, which is collapsed by default, so always showing it costs a
    // closed row. `isCampaignType` and `syncCampaign` were deleted with the condition — a reveal rule
    // for a field that is never hidden is dead code that reads as though it still governs something.
    // 🔴 WHO MAY NAME A PERSON — mirrors the server, and the server is what enforces it:
    // an existing card asks `task_perms.can_reassign` (AM+ anywhere, a team lead on anything they can
    // see — `_lead_may_act`); a new one asks `create_task`'s `may_delegate`, which as of 2026-08-14
    // is the same role test with no department condition attached.
    //
    // 🔴 The department condition that used to live on this line WAS THE SECOND HALF OF THE
    // "Team Lead can't assign" REPORT. A lead who filled in the form without touching Department got
    // `teamId == null`, so the picker locked with a message telling them that naming a person is "a
    // lead or manager call" — addressed to a team lead. The server refused the same request with the
    // same reasoning. Both were relaxed together; keep them that way.
    // This field was ungated until 2026-08-05 — the only one in the block that wasn't (Priority two
    // rows down always was) — so an employee could set it, hit Save, and lose the WHOLE edit to a
    // 403; on create the person they picked was silently dropped and the card landed on them.
    const mayNamePerson = () => (existing ? canReassign(existing) : (canManage || isLead));
    const LEAD_LOCKED = existing
      ? "Only an account manager, or a team lead, can change who leads this."
      : "Pick a department instead: its leads are notified and triage it. Naming a person is a lead or manager call.";
    // The Support multi-select's options. Mirrors the server's rule (routers/tasks.py
    // `_support_delegates`): a delegator may pick anyone; everyone else may only toggle THEMSELVES.
    // 🔴 A colleague already on the card renders `selected disabled` rather than being left out. Both
    // halves matter: omitting them would make a non-delegator's save look like "remove everyone else"
    // and lose the whole edit to a 403, while a plain `selected` would let them deselect a colleague
    // and hit the same 403. A disabled option is still submitted as selected, so the list round-trips
    // unchanged. (Same reasoning as the breakdown's locked step pickers.)
    function supportOptions(t) {
      const current = t.support_ids || [];
      const mayPick = mayNamePerson();
      return people
        .filter((p) => mayPick || p.id === S.user.id || current.indexOf(p.id) >= 0)
        .map((p) => {
          const on = current.indexOf(p.id) >= 0;
          const locked = !mayPick && p.id !== S.user.id;
          return `<option value="${p.id}"${on ? " selected" : ""}${locked ? " disabled" : ""}>`
            + `${S.esc(p.name)}${locked ? " — set by a lead" : ""}</option>`;
        });
    }
    // 🔴 "What the client will read" (#t-cnote) sits UP FRONT with the dates, not behind More
    // options: it is the entire content of the client's card. It had no field ANYWHERE in this form
    // until 2026-08-03, so every task published by Send to Atrium reached the client's board with an
    // empty note — the bridge sends `client_facing_notes`, and nothing here could set it. It sits
    // beside the internal Description on purpose: the pair reads as "what we tell ourselves" vs
    // "what they read", which is the whole client-safe split in two adjacent boxes.
    const m = S.modal({
      title: existing ? "Edit task" : "New task",
      wide: true,
      // 🔴 NOTHING ROUTING-RELATED IS COLLAPSED (2026-08-11). "Simple by default" (2026-07-27) put
      // name / description / dates on show and everything else behind "More options", which kept
      // filing to one field — and made the eleven fields that decide where a card GOES both one
      // click away and, being collapsed, unread. Work reached the board unrouted because the form
      // never asked. Client, department, lead, support, priority, campaign and service type are
      // visible rows now; only the four genuinely rare fields (and the origin correction) collapse.
      // Filing still needs a NAME and nothing else — every row below it is optional and every one
      // reads as skippable, which is what a labelled row buys that a boxed field does not.
      body: `<div class="tf">
        ${/* The name and description carry no box: the modal head already says this is a task, and a
              border around the loudest thing in the dialog only competes with it. `aria-label`
              rather than a visible label for the same reason — the placeholder and the pattern
              chips below say what it is, and a screen reader still gets a name. */""}
        <input id="t-name" class="tf-name" value="${S.esc(e.title || "")}" aria-label="Task name"
          placeholder="${S.esc(NAME_PLACEHOLDER)}" autocomplete="off">
        <div class="tf-pat" id="t-pat">
          <span class="seg">Campaign</span><span class="sep">|</span>
          <span class="seg">Action</span><span class="sep">|</span>
          <span class="seg">Detail</span>
          <span class="why">${NAME_HINT}</span>
        </div>
        <textarea id="t-desc" class="tf-desc" rows="2" aria-label="Description"
          placeholder="Add a sentence of context — optional">${S.esc(e.description || "")}</textarea>

        <div class="tf-rows">
          <div class="tf-row"><div class="k">${S.ICON.building}Client</div>
            <div class="v"><select id="t-client"><option value="">No client — internal work</option>${clients.map((c) => `<option value="${c.id}" ${c.id === e.client_id ? "selected" : ""}>${S.esc(c.name)}</option>`).join("")}</select></div></div>
          ${/* Project membership (2026-09-02) — options load async from /api/projects; the row
                only renders for roles holding projects.view, so nobody gets a dead picker. */""}
          ${S.hasCap("projects.view") ? `<div class="tf-row"><div class="k">${S.ICON.target}Project</div>
            <div class="v"><select id="t-project" data-cur="${e.project_id || ""}"><option value="">No project</option></select></div></div>` : ""}
          ${!existing && canManage ? `<div class="tf-row tall" id="t-share-wrap"${e.client_id ? "" : " hidden"}>
            <div class="k">${S.ICON.eye}Client sees it</div>
            <div class="v"><label class="tf-check"><input type="checkbox" id="t-share" checked> From day one, not once it is finished</label>
              <div class="rh">On by default (D6) — the client watches the work cross their board instead of meeting it finished. Untick to keep this one internal; you can share it later from the card.</div></div></div>` : ""}
          <div class="tf-row"><div class="k">${S.ICON.briefcase}Department</div>
            <div class="v"><select id="t-team"><option value="">Not routed yet</option>${teams.map((t) => `<option value="${t.id}" ${t.id === e.assigned_team_id ? "selected" : ""}>${S.esc(t.name)}</option>`).join("")}</select></div></div>
          <div class="tf-row" id="t-lead-row"><div class="k">${S.ICON.user}Lead</div>
            <div class="v">
              <select id="t-assignee"${mayNamePerson() ? "" : " disabled"} title="${mayNamePerson() ? "" : S.esc(LEAD_LOCKED)}"><option value="">Unassigned</option>${people.map((p) => `<option value="${p.id}" ${p.id === e.assigned_to_id ? "selected" : ""}>${S.esc(p.name)}</option>`).join("")}</select>
              <div class="rh" id="t-assignee-hint"${mayNamePerson() ? " hidden" : ""}>${LEAD_LOCKED}</div></div></div>
          ${/* SUPPORT — many people, none accountable. The same control the Atrium client-card
                form has always had; a Sentinel task had no equivalent, so the only way to put a
                second name on one was to invent a checklist step for them — which moved the
                progress bar, because that bar is done-steps ÷ total-steps. Staffing a card
                changed how finished it looked.
                A non-delegator still gets the picker (it lists only THEM, exactly like the
                breakdown's step owners) because joining and leaving work yourself has to stay
                open or the field is unusable by the people who pick work up. */""}
          ${/* 🔴 THE NATIVE `multiple` SELECT IS GONE (2026-08-14) — it was the worst control on this
                form. Three rows tall for a whole company, no faces, and selection by ctrl-click:
                a plain click on a second name silently DESELECTED the first, so the commonest way to
                staff two people quietly staffed one. It also could not show what the field means —
                Lead is accountable, Support is help — because both rendered as identical grey text.

                What replaces it is a checkbox list with faces and a filter, and the `<select>` is
                KEPT, hidden, as the value carrier. That is deliberate: the save path
                (`support_ids: Array.from(#t-support.options).filter(selected)`) and the whole
                `supportOptions` permission model — including `disabled` options for colleagues a
                non-delegator may not remove, which round-trip as still-selected — go on working
                untouched. A picker that rebuilt the payload itself would be a second copy of that
                rule, and this file's history is a list of what second copies cost. */""}
          <div class="tf-row tall"><div class="k">${S.ICON.users}Support</div>
            <div class="v">
              <select id="t-support" multiple hidden>${supportOptions(e).join("")}</select>
              <div class="ppick" id="t-support-pick">
                <div class="ppick-chips" id="t-support-chips"></div>
                <input type="search" class="ppick-q" id="t-support-q" placeholder="Search teammates…" autocomplete="off">
                <div class="ppick-list" id="t-support-list" role="group" aria-label="Support"></div>
              </div>
              <div class="rh">${mayNamePerson()
                ? "Anyone helping, as many as you need. They see the card and it counts toward their workload; the <b>Lead</b> stays accountable for it."
                : "You can add or remove <b>yourself</b>. Naming a colleague is a lead or manager call."}</div></div></div>
          ${canPrioritizeOnForm ? `<div class="tf-row"><div class="k">${S.ICON.target}Priority</div>
            <div class="v"><select id="t-priority">${vocab.priorities.map((p) => `<option ${p === (e.priority || "Medium") ? "selected" : ""}>${S.esc(p)}</option>`).join("")}</select></div></div>` : ""}
          ${/* Start and Due are ONE question, so they share a row. Each caption is a real <label>
                wrapping its own input — a bare `aria-label` would leave the two boxes unlabelled
                for everyone who can see them. */""}
          <div class="tf-row"><div class="k">${S.ICON.calendar}Dates</div>
            <div class="v tf-dates">
              <label class="tf-mini"><span>Starts</span><input type="date" id="t-start" value="${e.start_date || ""}"></label>
              <label class="tf-mini"><span>Due</span><input type="date" id="t-due" value="${e.due_date || ""}"></label></div></div>
          <div class="tf-row tall"><div class="k">${S.ICON.list}Campaign</div>
            <div class="v">
              <input id="t-campaign" value="${S.esc(e.campaign || "")}" placeholder="Groups cards — e.g. Stratos"
                list="t-campaign-list" autocomplete="off">
              <datalist id="t-campaign-list">${campaignNames(allTasks)
                .map((n) => `<option value="${S.esc(n)}"></option>`).join("")}</datalist>
              <div class="rh">Optional. Groups every card for one campaign — including the one-line
                jobs raised after it launched, which is all that still connects them. Pick an
                existing name rather than retyping it.</div></div></div>
          ${!existing ? `<div class="tf-row tall"><div class="k">${S.ICON.doc}Service type</div>
            <div class="v"><select id="t-svc"><option value="">Custom — start empty</option></select>
              <div class="rh">Pick a department first. The phases, steps and labels are created for you.</div></div></div>` : ""}
        </div>
        ${!existing ? `<div id="t-svc-preview" style="margin-top:13px" hidden></div>` : ""}

        ${/* 🔴 "What the client will read" sits UP FRONT, in its own block, not behind anything: it
              is the entire content of the client's card. It had no field ANYWHERE in this form until
              2026-08-03, so every task published by Send to Atrium reached the client's board with an
              empty note — the bridge sends `client_facing_notes`, and nothing here could set it. It
              is one block rather than a tenth row because it is the only field in this form the
              client ever sees, and because the internal Description above it is the other half of
              the pair: what we tell ourselves vs what they read. */""}
        <div class="tf-cs">
          <div class="lb">${S.ICON.eye}What the client will read <i>— this is their whole card</i></div>
          <textarea id="t-cnote" rows="2" placeholder="Plain language, no internal detail. Blank means they see a title and nothing else.">${S.esc(e.client_facing_notes || "")}</textarea>
        </div>

        <details class="tk-extra tf-more"${extrasOpen ? " open" : ""}>
          <summary>Rarely needed — charge, content type, deliverable link, internal notes</summary>
          <div class="two">
            <label class="field"><span>Service charge ($)</span><input id="t-charge" inputmode="decimal" value="${S.esc(e.service_charge || "")}" placeholder="0" pattern="[0-9]*[.]?[0-9]*" title="Optional — numbers only (e.g. 4200 or 4200.50)"></label>
            <label class="field"><span>Content type</span><input id="t-ctype" value="${S.esc(e.content_type || "")}"></label>
          </div>
          ${/* 🔴 A CORRECTION, on an EXISTING card only, and only for somebody who could reassign
                it — the same gate the server applies (`can_reassign`), because this feeds the
                Monitor's reactive-load number. It is deliberately absent on CREATE: the server
                classifies from who is filing for whom (services/task_origin), and offering the
                answer as a form field on a new task would turn a derived fact into a guess
                somebody has to make while capturing an urgent job.
                "Not set" is a real option: it is what every pre-column task holds, and a manager
                must be able to put a card back to unclassified rather than pick a side. */""}
          ${existing && canReassign(existing) ? `<label class="field"><span>Raised as</span>
            <select id="t-origin">
              <option value=""${e.origin ? "" : " selected"}>Not set</option>
              ${Object.keys(ORIGIN_LABEL).map((k) => `<option value="${k}"${e.origin === k ? " selected" : ""}>${ORIGIN_LABEL[k]}</option>`).join("")}
            </select>
            <div class="form-hint">Planned before the day started, or added once it came up. Set
              automatically when the card is created; change it here if that was wrong.</div></label>` : ""}
          <label class="field"><span>Deliverable URL (client-safe)</span><input id="t-deliv" value="${S.esc(e.deliverable_url || "")}"></label>
          <label class="field" style="margin-bottom:0"><span>${S.ICON.lock}Internal notes</span><textarea id="t-inotes" rows="3">${S.esc(e.internal_notes || "")}</textarea></label>
        </details>
      </div>`,
      footer: `<span class="tf-kbd"><kbd>Ctrl</kbd>+<kbd>Enter</kbd> to ${existing ? "save" : "create"}</span>`
        + `<button class="btn ghost" id="t-cancel">Cancel</button>`
        + `<button class="btn primary" id="t-save">${existing ? "Save changes" : "Create task"}</button>`,
    });
    S.qs("#t-cancel").onclick = m.close;
    // The kicker is added AFTER the fact because `S.modal` escapes its `title` — deliberately, since
    // that is the one string a caller may build from data — so there is no way to pass markup in.
    // Prepending it to the h3 (which the .tf-modal rule turns into a two-line column) keeps the
    // dialog's accessible name intact: "Task board / New task", one heading, in reading order.
    const tfHead = m.root.querySelector(".modal");
    if (tfHead) {
      tfHead.classList.add("tf-modal");
      const h = tfHead.querySelector(".modal-head h3");
      if (h) h.insertAdjacentHTML("afterbegin", `<span class="tf-kicker">Task board</span>`);
    }
    // `autofocus` is unreliable on a node injected after load, so put the caret in the name field
    // explicitly. The name is still the only field filing REQUIRES, so this plus Ctrl+Enter is the
    // whole fast path — type a task and submit without touching the mouse or the nine rows below.
    const nameBox = S.qs("#t-name");
    if (nameBox) nameBox.focus();

    // The naming rule, shown as it is followed: each part of "Campaign | Action | Detail" fills in
    // as its pipe is typed. 🔴 STILL NOT A VALIDATOR — see NAME_HINT. Nothing here gates Save, and a
    // blank name still saves as "Untitled task", because a form that refuses a badly-shaped title
    // loses the unplanned work §3 of the guidelines is entirely about capturing.
    const patSegs = S.qsa("#t-pat .seg");
    const syncPattern = () => {
      const parts = (nameBox.value || "").split("|");
      patSegs.forEach((el, i) => el.classList.toggle("on", !!(parts[i] || "").trim()));
    };
    if (nameBox && patSegs.length) { nameBox.addEventListener("input", syncPattern); syncPattern(); }

    // Share-on-create only means anything once there is a client to share WITH, so the control
    // follows the Client select rather than sitting there greyed out.
    const clientBox = S.qs("#t-client");
    const syncShare = () => {
      const wrap = S.qs("#t-share-wrap");
      if (wrap) wrap.hidden = !clientBox.value;
    };
    if (clientBox) clientBox.addEventListener("change", syncShare);

    // 🔴 THE DEPARTMENT NO LONGER GATES THIS FIELD (2026-08-14). Until then a lead's right to name
    // somebody followed the department being filed into, so this picker had to re-evaluate on every
    // change of the Department select — and a lead who never touched that select got a locked picker
    // and the message "Naming a person is a lead or manager call". That was the client half of the
    // reported "Team Lead can't assign"; `create_task.may_delegate` was relaxed with it.
    //
    // `syncAssignee` is kept and still runs ONCE, because the lock is real for employees and interns
    // — it just no longer depends on anything the user can change mid-form, so there is nothing left
    // to re-sync and the `change` listener that used to drive it would now be a no-op that reads as
    // though it still governs something.
    const assigneeBox = S.qs("#t-assignee");
    const syncAssignee = () => {
      const allowed = mayNamePerson();
      assigneeBox.disabled = !allowed;
      assigneeBox.title = allowed ? "" : LEAD_LOCKED;
      const hint = S.qs("#t-assignee-hint");
      if (hint) hint.hidden = allowed;
      // Never leave a name sitting in a locked picker: the server REFUSES it rather than quietly
      // dropping it, and a save that dies on a field they cannot even reach is no better than the
      // silent version.
      if (!allowed) assigneeBox.value = "";
    };
    syncAssignee();

    // --- Support picker (2026-08-14) --------------------------------------------------------
    // Draws the hidden `#t-support` multi-select as faces + checkboxes. 🔴 THE SELECT REMAINS THE
    // SINGLE SOURCE OF TRUTH: every toggle writes `option.selected` and every repaint reads it back,
    // so the form's existing save path and `supportOptions`' permission rules (a `disabled` option is
    // a colleague this user may not remove, and must stay selected) need no counterpart here.
    (function wireSupportPicker() {
      const sel = S.qs("#t-support");
      const list = S.qs("#t-support-list");
      const chips = S.qs("#t-support-chips");
      const q = S.qs("#t-support-q");
      if (!sel || !list) return;
      const opts = Array.from(sel.options);
      // A short list needs no search box — the filter would be one more control than the task.
      if (opts.length <= 6 && q) q.hidden = true;

      function paint() {
        const term = (q && q.value || "").trim().toLowerCase();
        const chosen = opts.filter((o) => o.selected);
        // The lead is shown among the chips, distinctly, because "who is on this card" is the
        // question being answered and the answer is incomplete without them. It is NOT a support
        // chip and cannot be removed here — that is the Lead row's job, one field up.
        const leadId = assigneeBox && assigneeBox.value ? Number(assigneeBox.value) : null;
        const lead = leadId ? peopleById[leadId] : null;
        chips.innerHTML =
          (lead ? `<span class="ppick-chip is-lead" title="Accountable for this card — change it in the Lead row above">${S.avatar(lead, "xs")}${S.esc(lead.name)}<em>lead</em></span>` : "")
          + (chosen.length
            ? chosen.map((o) => {
                const p = peopleById[Number(o.value)];
                return `<span class="ppick-chip" data-v="${o.value}">${S.avatar(p, "xs")}${S.esc(p ? p.name : o.textContent)}${
                  o.disabled ? "" : `<button type="button" class="ppick-x" data-off="${o.value}" aria-label="Remove ${S.esc(p ? p.name : "")}">✕</button>`}</span>`;
              }).join("")
            : (lead ? "" : `<span class="ppick-none">Nobody assigned yet</span>`));

        const rows = opts.filter((o) => {
          const p = peopleById[Number(o.value)];
          return !term || (p ? p.name : o.textContent).toLowerCase().includes(term);
        });
        list.innerHTML = rows.length ? rows.map((o) => {
          const p = peopleById[Number(o.value)];
          return `<label class="ppick-row${o.disabled ? " locked" : ""}"${o.disabled ? ` title="Named by a lead — you can't remove them"` : ""}>
            <input type="checkbox" value="${o.value}"${o.selected ? " checked" : ""}${o.disabled ? " disabled" : ""}>
            ${S.avatar(p, "xs")}<span class="nm">${S.esc(p ? p.name : o.textContent)}</span>
            ${p && p.id === S.user.id ? `<em class="ppick-you">you</em>` : ""}
          </label>`;
        }).join("") : `<div class="ppick-none">No teammate matches “${S.esc(term)}”.</div>`;

        list.querySelectorAll("input[type=checkbox]").forEach((cb) => {
          cb.onchange = () => {
            const o = opts.find((x) => x.value === cb.value);
            if (o && !o.disabled) o.selected = cb.checked;
            paint();
          };
        });
        chips.querySelectorAll(".ppick-x").forEach((b) => {
          b.onclick = (ev) => {
            ev.preventDefault();
            const o = opts.find((x) => x.value === b.dataset.off);
            if (o && !o.disabled) o.selected = false;
            paint();
          };
        });
      }
      if (q) q.oninput = paint;
      // The lead chip has to follow the Lead select, or the summary of "who is on this card"
      // silently goes stale the moment somebody changes it.
      if (assigneeBox) assigneeBox.addEventListener("change", paint);
      paint();
    })();

    // Service-type picker (new tasks only): filter recipes by the chosen department, preview the
    // checklist it will seed, and prefill the content type. The server does the actual seeding.
    const svcSel = S.qs("#t-svc");
    if (svcSel) {
      const preview = S.qs("#t-svc-preview");
      const updatePreview = () => {
        const tpl = templates.find((t) => t.key === svcSel.value);
        if (!tpl) { preview.hidden = true; preview.innerHTML = ""; return; }
        preview.hidden = false;
        preview.innerHTML = `<div class="section-label">Auto checklist · ${tpl.steps.length} steps</div>
          <ul class="svc-preview">${tpl.steps.map((s) => `<li>${S.esc(s)}</li>`).join("")}</ul>`;
        // Prefill the template's defaults, but never clobber something the user already set.
        // Labels are no longer a manual field — the server seeds them from the template's
        // default_labels whenever the create request carries none (see routers/tasks.py).
        const ct = S.qs("#t-ctype"); if (ct && !ct.value) ct.value = tpl.content_type || "";
        const prio = S.qs("#t-priority"); if (prio && tpl.default_priority && prio.value === "Medium") prio.value = tpl.default_priority;
        const desc = S.qs("#t-desc"); if (desc && !desc.value.trim() && tpl.default_description) desc.value = tpl.default_description;
      };
      const fillServices = () => {
        const opts = templatesForTeam(numOrNull("t-team"));
        svcSel.innerHTML = `<option value="">Custom (blank)</option>` +
          opts.map((o) => `<option value="${S.esc(o.key)}">${S.esc(o.label)}</option>`).join("");
        svcSel.disabled = !opts.length;
        updatePreview();
      };
      S.qs("#t-team").addEventListener("change", fillServices);
      svcSel.addEventListener("change", updatePreview);
      fillServices();
    }

    // 🔴 Ctrl/Cmd+Enter SUBMITS, and it has to be bound to the OVERLAY rather than the document:
    // this form can be open under a confirm (Delete from the drawer), and a document-level handler
    // would fire for whichever modal is on top. `m.root` is this dialog's own overlay.
    // Deliberately Ctrl/Cmd+Enter and not plain Enter: the description, client note and internal
    // notes are textareas, where Enter means a new line.
    m.root.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); save(); }
    });
    S.qs("#t-save").onclick = save;
    // A shortcut is easy to fire twice, and on CREATE a second POST is a duplicate card rather than
    // a repeated edit — so the in-flight guard is not optional now that there are two ways to submit.
    // Project options, filled async — active projects plus whichever one the card already
    // carries (so editing an archived project's card never silently unlinks it).
    const projSel = S.qs("#t-project");
    if (projSel) S.api("/api/projects").then((d) => {
      const cur = projSel.dataset.cur;
      projSel.innerHTML = `<option value="">No project</option>` + (d.projects || [])
        .filter((p) => p.status === "active" || String(p.id) === cur)
        .map((p) => `<option value="${p.id}" ${String(p.id) === cur ? "selected" : ""}>${S.esc(p.name)}</option>`).join("");
    }).catch(() => { const r = projSel.closest(".tf-row"); if (r) r.hidden = true; });
    let saving = false;
    async function save() {
      if (saving) return;
      // The name field is the NAME. `campaign` is a separate, optional grouping field and is sent
      // as null when blank — writing the title into both is the bug this replaced (§7 of
      // docs/TASKBOARD_REBUILD.md). Labels aren't sent (the server seeds them from the service
      // template). The name is never forced: blank falls back to "Untitled task" (rename any time).
      const name = val("t-name") || "Untitled task";
      const payload = {
        title: name, campaign: val("t-campaign"), client_id: numOrNull("t-client"),
        ...(S.qs("#t-project") ? { project_id: numOrNull("t-project") } : {}),
        assigned_team_id: numOrNull("t-team"), assigned_to_id: numOrNull("t-assignee"),
        content_type: val("t-ctype"), due_date: val("t-due") || null,
        start_date: val("t-start") || null,
        service_charge: val("t-charge") || null,
        description: val("t-desc"), deliverable_url: val("t-deliv"), internal_notes: val("t-inotes"),
        // The client-safe note. Sent as "" rather than null when cleared, so emptying the box
        // actually clears the client's card instead of leaving the old text stranded there.
        client_facing_notes: S.qs("#t-cnote").value,
        // SUPPORT. Always sent as an array — `[]` means "nobody", which is a real edit (removing the
        // last supporter). The server treats an ABSENT field as "leave them alone", so sending null
        // here would make clearing the list impossible; the same distinction `client_facing_notes`
        // above makes between "" and null.
        support_ids: Array.from(S.qs("#t-support").options)
          .filter((o) => o.selected).map((o) => Number(o.value)),
      };
      // `status` is sent on CREATE only (the column a new card lands in). An edit never sends it —
      // moving a card is the board's job, not this form's. See `newStatus`.
      if (!existing) payload.status = newStatus;
      if (!existing && svcSel) payload.service_key = svcSel.value || null;
      if (canPrioritizeOnForm) payload.priority = S.qs("#t-priority").value;
      // Only when the control is on the form (an existing card, a manager). `null` for "Not set" —
      // `update_task` uses `exclude_unset`, so an explicit null is what actually clears it back to
      // unclassified, whereas "" would be normalized away and silently leave the old value.
      if (S.qs("#t-origin")) payload.origin = S.qs("#t-origin").value || null;
      // Share-on-create (D6). Sent ONLY on create, and only when the control exists — the server
      // treats an absent value as "decide for me" (share when there is a client), so an omitted
      // field is not the same as false and must not be forged into one.
      const shareBox = S.qs("#t-share");
      if (!existing && shareBox) payload.share_with_client = shareBox.checked;
      const btn = S.qs("#t-save");
      saving = true; btn.disabled = true;
      try {
        if (existing) await S.api("/api/tasks/" + existing.id, { method: "PATCH", body: payload });
        else await S.api("/api/tasks", { method: "POST", body: payload });
        S.toast(existing ? "Task updated" : "Task created", "ok"); m.close(); load();
      } catch (err) {
        // The modal stays OPEN on failure — the whole point of not closing first is that the typed
        // work survives a 403 or a dropped connection — so the guard has to be released here.
        saving = false; btn.disabled = false;
        S.toast(err.detail, "err");
      }
    }
    function val(id) { return S.qs("#" + id).value || null; }
    function numOrNull(id) { const v = S.qs("#" + id).value; return v ? Number(v) : null; }
  }

  await load();
  // Deep-links: ?open=<id> (notification) and ?new=1 (command palette) — read from the current
  // URL, which is /dashboard now that the board is embedded there (/tasks 302s here too).
  const params = new URLSearchParams(location.search);
  if (params.get("open")) openTask(params.get("open"));
  if (params.get("new") && canCreate) taskForm(null);

  // Live board: reload when someone ELSE changes a task (SSE). Our own changes are already
  // reflected optimistically, so we skip events we caused. Debounced to coalesce bursts.
  if (window.EventSource) {
    let reloadTimer;
    const es = new EventSource("/api/stream");
    es.addEventListener("task", (e) => {
      let actor = null;
      try { actor = JSON.parse(e.data).actor_id; } catch (_) { /* ignore */ }
      if (actor === S.user.id) return;
      clearTimeout(reloadTimer);
      reloadTimer = setTimeout(load, 400);
    });
    window.addEventListener("beforeunload", () => es.close());
  }

  return {
    /** Apply the Overview's page-wide people scope. A pure re-render: the cards are already in
     *  hand and the server has already decided which of them this viewer may see, so narrowing
     *  is local and instant — no refetch, no flicker, no second permission decision. */
    setScope(next) {
      scope = normaliseScope(next);
      render();
    },
  };
  },
};
