/* GrowthMath — the dimension list and the pace/speed arithmetic, shared by every surface that
   shows a growth number: the Overview's four rings and its pace band (growth.js), the manager's
   read-only view of somebody else (growth-page.js, via growth.js), and the admin Team-progress
   table (teamgrowth.js).

   It exists because these numbers are COMPARED. A worker's own ring says "▲ 20 ahead" and their
   row in the admin table has to say the same thing about the same day, or one of the two surfaces
   is quietly wrong and nobody can tell which. Two copies of a formula is how that starts.

   Nothing here touches the DOM or the API — pure functions over (actual %, deadline), so it can be
   loaded by any page and reasoned about on its own.

   THE THREE MEASURES, which are genuinely different questions:
     actual    — where you are. The Mastery Engine's score, never typed by hand.
     expected  — where the calendar says you'd be, running linearly from the programme start to
                 this dimension's deadline. `actual − expected` is the ▲/▼ pace chip: a POSITION.
     speed     — points of mastery gained per WEEK, measured from the engine's attempt log over a
                 window (see services/team_growth.py). A RATE. Someone can sit comfortably "ahead"
                 on pace having done nothing for a month; only speed catches that. */
window.GrowthMath = (() => {
  // The four growth dimensions, in reading order. Hues live in styles.css as --dim-<key> so dark
  // mode can retune them. ('philosophical' replaced 'mental' 2026-07-27; rows were data-migrated.)
  const DIMS = [
    { key: "spiritual", name: "Spiritual", icon: "flame", blurb: "Faith & inner life" },
    { key: "professional", name: "Professional", icon: "target", blurb: "Craft & career" },
    { key: "philosophical", name: "Philosophical", icon: "cap", blurb: "Mindsets & mental models" },
    { key: "physical", name: "Physical", icon: "heart", blurb: "Body & training" },
  ];
  const DIM_KEYS = DIMS.map((d) => d.key);

  // The pace window every dimension races on: a fixed start (when the four-tab system began) to
  // the dimension's own deadline — editable on the pace band, stored per dimension per person.
  const START_DEFAULT = "2026-07-27";
  const DEADLINE_DEFAULT = "2026-11-04";

  const dimName = (key) => (DIMS.find((d) => d.key === key) || {}).name || key;

  /** Expected-by-today %: linear from the programme start to `deadline` (blank = the default). */
  function expected(deadline) {
    const start = new Date(START_DEFAULT + "T00:00:00").getTime();
    const end = new Date((deadline || DEADLINE_DEFAULT) + "T23:59:59").getTime();
    if (!(end > start)) return 100;
    return Math.max(0, Math.min(100, ((Date.now() - start) / (end - start)) * 100));
  }

  /** Weeks left until `deadline`, floored just above zero so a rate never divides by nothing. */
  function weeksLeft(deadline) {
    const end = new Date((deadline || DEADLINE_DEFAULT) + "T23:59:59").getTime();
    return Math.max(1 / 7, (end - Date.now()) / 6048e5);
  }

  /** Points per week this person still needs to average to land on 100% by the deadline.
   *  This is what makes a speed READABLE: 2 pts/wk is fast for someone at 95% and a stall for
   *  someone at 10%. Returns null when there's no actual to work from. */
  function paceNeeded(actual, deadline) {
    if (actual == null) return null;
    return Math.max(0, (100 - actual) / weeksLeft(deadline));
  }

  /** Points ahead (+) or behind (−) the calendar, or null when either side is unknown. */
  function paceDelta(actual, exp) {
    if (actual == null || exp == null) return null;
    return actual - exp;
  }

  /** The shared ahead/behind verdict as plain text, for a title attribute. ±2 reads as "on pace". */
  function paceText(actual, exp) {
    const raw = paceDelta(actual, exp);
    if (raw == null) return "";
    const d = Math.round(raw);
    if (Math.abs(d) <= 2) return "on pace";
    return d > 0 ? `${d} ahead` : `${Math.abs(d)} behind`;
  }

  /** The same verdict as a chip. Within ±2 points reads as "on pace". */
  function paceChip(actual, exp) {
    const raw = paceDelta(actual, exp);
    if (raw == null) return "";
    const d = Math.round(raw);
    if (Math.abs(d) <= 2) return `<span class="pace-chip on">on pace</span>`;
    return d > 0
      ? `<span class="pace-chip ahead">▲ ${d} ahead</span>`
      : `<span class="pace-chip behind">▼ ${Math.abs(d)} behind</span>`;
  }

  /* --- speed ---------------------------------------------------------------------------------
     Bands are RELATIVE to what each person still needs (paceNeeded), not to a flat threshold —
     see the comment on paceNeeded. `unknown` is its own band and must never be styled or sorted
     as though it were zero: it means the engine had nothing to say (an outage, or someone with no
     enrolled programme), and reading that as "did nothing" is a confident lie about a real
     person. Physical velocity is permanently unknown by design — nothing timestamps a PR. */
  const BANDS = {
    unknown: { label: "no data", cls: "unknown" },
    stalled: { label: "stalled", cls: "stalled" },
    slow: { label: "slow", cls: "slow" },
    ontrack: { label: "on track", cls: "ontrack" },
    fast: { label: "fast", cls: "fast" },
  };

  function speedBand(velocity, needed) {
    if (velocity == null) return "unknown";
    if (velocity <= 0.05) return "stalled";
    if (needed == null || needed <= 0) return velocity >= 1 ? "fast" : "ontrack";
    const ratio = velocity / needed;
    if (ratio < 0.5) return "slow";
    if (ratio < 1) return "ontrack";
    return "fast";
  }

  /** "+4.2 / wk", "0 / wk", or "—" when it isn't measurable. Never renders unknown as a zero. */
  function fmtSpeed(velocity) {
    if (velocity == null) return "—";
    const v = Math.round(velocity * 10) / 10;
    return `${v > 0 ? "+" : ""}${v} / wk`;
  }

  function speedChip(velocity, actual, deadline) {
    const band = speedBand(velocity, paceNeeded(actual, deadline));
    const b = BANDS[band];
    return `<span class="speed-chip ${b.cls}" title="${band === "unknown"
      ? "No Mastery Engine data for this person — not the same as no progress"
      : `Needs about ${Math.round((paceNeeded(actual, deadline) || 0) * 10) / 10} pts/wk to finish by ${deadline || DEADLINE_DEFAULT}`}">${fmtSpeed(velocity)}</span>`;
  }

  return {
    DIMS, DIM_KEYS, START_DEFAULT, DEADLINE_DEFAULT, BANDS,
    dimName, expected, weeksLeft, paceNeeded,
    paceDelta, paceText, paceChip,
    speedBand, fmtSpeed, speedChip,
  };
})();
