/* Sentinel charts — tiny, dependency-free SVG charts for the dashboard.
   No CDN/canvas: inline SVG so it works offline + under the strict CSP. Follows the house
   dataviz rules: recessive axes, 2px gaps between fills, rounded data-ends anchored to the
   baseline, an always-present legend for multi-series, per-mark hover tooltips, a table view,
   and a VALIDATED status palette that re-picks itself for light/dark. */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const svgEl = (t, a) => { const e = document.createElementNS(NS, t); for (const k in a) e.setAttribute(k, a[k]); return e; };
  const isDark = () => document.documentElement.getAttribute("data-theme") === "dark";

  // Status palette — validated (node scripts/validate_palette.js) for each surface.
  // light on #FFF: CVD ok, contrast relieved by legend+labels+table. dark on #111C15: CVD 12.1, contrast pass.
  const ATT = {
    light: { ontime: "#54B948", late: "#F59E0B", absent: "#EF4444" },
    dark:  { ontime: "#4CAF43", late: "#E0930F", absent: "#EF5A5A" },
  };
  const BAR_HUE = { light: "#54B948", dark: "#6BCB4E" };
  const SERIES = [["ontime", "On-time"], ["late", "Late"], ["absent", "Absent"]];

  // ---- shared tooltip ----
  let tip;
  function showTip(html, x, y) {
    if (!tip) { tip = document.createElement("div"); tip.className = "chart-tip"; document.body.appendChild(tip); }
    tip.innerHTML = html; tip.style.display = "block";
    tip.style.left = Math.round(x + 12) + "px"; tip.style.top = Math.round(y + 12) + "px";
  }
  const hideTip = () => { if (tip) tip.style.display = "none"; };

  // ---- one-time styles (theme-aware via tokens) ----
  const style = document.createElement("style");
  style.textContent = `
    .chart-card .chart-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:6px}
    .chart-card .chart-head h3{margin:0}
    .chart-legend{display:flex;flex-wrap:wrap;gap:14px;margin-top:8px}
    .chart-legend .lg{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--sub);font-weight:600}
    .chart-legend .sw{width:10px;height:10px;border-radius:3px;display:inline-block}
    .chart-svg{width:100%;height:auto;display:block;overflow:visible}
    .chart-svg text{font-family:Inter,sans-serif}
    .chart-seg{transition:opacity .12s} .chart-seg:hover{opacity:.82;cursor:default}
    .chart-tip{position:fixed;z-index:9999;display:none;pointer-events:none;background:var(--card);
      color:var(--ink);border:1px solid var(--line-strong);border-radius:10px;padding:8px 10px;
      font:600 12px Inter,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.18);max-width:240px}
    .chart-tip .tt-row{display:flex;align-items:center;gap:7px;color:var(--sub);font-weight:600}
    .chart-tip .tt-row b{color:var(--ink);margin-left:auto}
    .chart-tip .tt-sw{width:9px;height:9px;border-radius:2px}
    .chart-tbl{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}
    .chart-tbl th,.chart-tbl td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}
    .chart-tbl th:first-child,.chart-tbl td:first-child{text-align:left}
    .chart-toggle{font-size:12px;color:var(--sub);background:none;border:1px solid var(--line);
      border-radius:999px;padding:3px 11px;cursor:pointer;font-weight:600}
    .chart-toggle:hover{border-color:var(--line-strong);color:var(--ink)}
    .chart-empty{color:var(--muted);padding:26px;text-align:center}`;
  document.head.appendChild(style);

  // Registry so charts recolor when the theme toggles (no reload needed).
  const registry = [];
  function mountChart(host, title, legendHtml, renderPlot, renderTable) {
    host.classList.add("chart-card");
    let showingTable = false;
    const draw = () => {
      host.innerHTML = `<div class="chart-head"><h3>${esc(title)}</h3>
        <button class="chart-toggle" type="button">${showingTable ? "Chart" : "Table"}</button></div>`;
      const btn = host.querySelector(".chart-toggle");
      btn.onclick = () => { showingTable = !showingTable; draw(); };
      if (showingTable) { host.insertAdjacentHTML("beforeend", renderTable()); return; }
      host.appendChild(renderPlot());
      if (legendHtml) host.insertAdjacentHTML("beforeend", legendHtml);
    };
    registry.push({ host, draw });
    draw();
  }
  new MutationObserver(() => registry.forEach((r) => { if (document.body.contains(r.host)) r.draw(); }))
    .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  function niceMax(v) {
    if (v <= 5) return Math.max(1, v);
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    return Math.ceil(v / (p / 2)) * (p / 2);
  }
  const roundedTop = (x, y, w, h, r) => {
    r = Math.min(r, h, w / 2);
    return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
  };
  const shortDay = (iso) => { const d = new Date(iso + "T00:00:00+08:00"); return d.getDate(); };
  const wday = (iso) => new Date(iso + "T00:00:00+08:00").toLocaleDateString("en-PH", { timeZone: "Asia/Manila", weekday: "short" });

  // ============ Attendance trend (stacked bars) ============
  function attendanceTrend(host, trend) {
    if (!trend || !trend.length) { host.classList.add("chart-card"); host.innerHTML = `<div class="chart-head"><h3>Attendance, last 14 days</h3></div><div class="chart-empty">No attendance yet.</div>`; return; }

    const legendHtml = () => { const c = ATT[isDark() ? "dark" : "light"]; return `<div class="chart-legend">${SERIES.map(([k, lbl]) => `<span class="lg"><span class="sw" style="background:${c[k]}"></span>${lbl}</span>`).join("")}</div>`; };

    const renderPlot = () => {
      const c = ATT[isDark() ? "dark" : "light"];
      const W = 720, H = 250, padL = 34, padR = 10, padT = 12, padB = 30;
      const x0 = padL, x1 = W - padR, y0 = padT, y1 = H - padB, plotW = x1 - x0, plotH = y1 - y0;
      const max = niceMax(Math.max(1, ...trend.map((d) => d.ontime + d.late + d.absent)));
      const svg = svgEl("svg", { class: "chart-svg", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Attendance last 14 days" });
      // gridlines + y labels (recessive)
      for (let i = 0; i <= 4; i++) {
        const val = Math.round(max * i / 4), gy = y1 - plotH * i / 4;
        svg.appendChild(svgEl("line", { x1: x0, y1: gy, x2: x1, y2: gy, stroke: "var(--line)", "stroke-width": 1 }));
        const t = svgEl("text", { x: x0 - 6, y: gy + 3.5, "text-anchor": "end", "font-size": 10, fill: "var(--muted)" }); t.textContent = val; svg.appendChild(t);
      }
      const slot = plotW / trend.length, bw = Math.min(30, slot * 0.62);
      trend.forEach((d, i) => {
        const cx = x0 + slot * i + slot / 2, bx = cx - bw / 2;
        let cursorY = y1;
        const segs = [["ontime", d.ontime], ["late", d.late], ["absent", d.absent]];
        const topIdx = segs.reduce((acc, s, idx) => (s[1] > 0 ? idx : acc), -1);
        segs.forEach(([k, v], idx) => {
          if (v <= 0) return;
          let h = (v / max) * plotH; const gap = 2;
          const drawH = Math.max(1, h - (idx === topIdx ? 0 : gap));
          const ty = cursorY - h;
          let node;
          if (idx === topIdx) { node = svgEl("path", { d: roundedTop(bx, ty, bw, Math.max(1, h - 0), 4), fill: c[k], class: "chart-seg" }); }
          else { node = svgEl("rect", { x: bx, y: ty, width: bw, height: drawH, fill: c[k], class: "chart-seg" }); }
          const label = SERIES.find((s) => s[0] === k)[1];
          node.addEventListener("mousemove", (e) => showTip(
            `<div style="color:var(--ink);font-weight:700;margin-bottom:4px">${wday(d.date)} ${shortDay(d.date)}</div>
             <div class="tt-row"><span class="tt-sw" style="background:${c[k]}"></span>${label}<b>${v}</b></div>
             <div class="tt-row" style="margin-top:2px">Total present<b>${d.ontime + d.late}</b></div>`, e.clientX, e.clientY));
          node.addEventListener("mouseleave", hideTip);
          svg.appendChild(node); cursorY -= h;
        });
        // x label (day of month), weekends dimmed
        const t = svgEl("text", { x: cx, y: y1 + 16, "text-anchor": "middle", "font-size": 10, fill: d.workday ? "var(--sub)" : "var(--muted)" });
        t.textContent = shortDay(d.date); svg.appendChild(t);
      });
      return svg;
    };

    const renderTable = () => `<table class="chart-tbl"><thead><tr><th>Date</th><th>On-time</th><th>Late</th><th>Absent</th></tr></thead>
      <tbody>${trend.map((d) => `<tr><td>${wday(d.date)} ${shortDay(d.date)}</td><td>${d.ontime}</td><td>${d.late}</td><td>${d.absent}</td></tr>`).join("")}</tbody></table>`;

    mountChart(host, "Attendance, last 14 days", null, () => { const f = document.createDocumentFragment(); f.appendChild(renderPlot()); const l = document.createElement("div"); l.innerHTML = legendHtml(); f.appendChild(l.firstChild); return f; }, renderTable);
  }

  // ============ Open tasks by status (horizontal bars, single hue) ============
  function tasksByStatus(host, rows) {
    if (!rows || !rows.length) { host.classList.add("chart-card"); host.innerHTML = `<div class="chart-head"><h3>Open tasks by status</h3></div><div class="chart-empty">No open tasks.</div>`; return; }
    const renderPlot = () => {
      const hue = BAR_HUE[isDark() ? "dark" : "light"];
      const rowH = 30, W = 720, padL = 128, padR = 40, padT = 6;
      const H = padT * 2 + rows.length * rowH, x0 = padL, x1 = W - padR, plotW = x1 - x0;
      const max = Math.max(1, ...rows.map((r) => r.count));
      const svg = svgEl("svg", { class: "chart-svg", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Open tasks by status" });
      rows.forEach((r, i) => {
        const cy = padT + i * rowH + rowH / 2, w = Math.max(2, (r.count / max) * plotW), bh = 16;
        const lbl = svgEl("text", { x: x0 - 10, y: cy + 4, "text-anchor": "end", "font-size": 12, fill: "var(--sub)", "font-weight": 600 }); lbl.textContent = r.status; svg.appendChild(lbl);
        const bar = svgEl("rect", { x: x0, y: cy - bh / 2, width: w, height: bh, rx: 4, fill: hue, class: "chart-seg" });
        bar.addEventListener("mousemove", (e) => showTip(`<div class="tt-row">${esc(r.status)}<b>${r.count}</b></div>`, e.clientX, e.clientY));
        bar.addEventListener("mouseleave", hideTip); svg.appendChild(bar);
        const val = svgEl("text", { x: x0 + w + 7, y: cy + 4, "font-size": 12, fill: "var(--ink)", "font-weight": 700 }); val.textContent = r.count; svg.appendChild(val);
      });
      return svg;
    };
    const renderTable = () => `<table class="chart-tbl"><thead><tr><th>Status</th><th>Open tasks</th></tr></thead>
      <tbody>${rows.map((r) => `<tr><td>${esc(r.status)}</td><td>${r.count}</td></tr>`).join("")}</tbody></table>`;
    mountChart(host, "Open tasks by status", null, renderPlot, renderTable);
  }

  window.SentinelCharts = { attendanceTrend, tasksByStatus };
})();
