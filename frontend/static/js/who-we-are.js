/* Manifesto interactions for who-we-are.html (the "Our North Star" page).
   Extracted from an inline <script> so it complies with the app's CSP (script-src 'self') —
   an inline block is blocked, which left every reveal-on-scroll (.rv) element stuck at opacity:0
   and the page looking empty. Loaded with a plain <script src>, this runs normally. */
// reveal on scroll
const io = new IntersectionObserver((es) => {
  es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
}, { threshold: 0.14, rootMargin: "0px 0px -8% 0px" });
document.querySelectorAll(".rv").forEach((el, i) => { el.style.transitionDelay = (Math.min(i % 6, 5) * 55) + "ms"; io.observe(el); });

// count-up for proof numbers
const reduce = window.matchMedia("(prefers-reduced-motion:reduce)").matches;
function countUp(el) {
  const target = +el.dataset.count;
  const suf = el.dataset.suffix || "";
  const u = el.querySelector(".u");
  const dur = 1100;
  const t0 = performance.now();
  function tick(t) {
    let p = Math.min((t - t0) / dur, 1);
    p = 1 - Math.pow(1 - p, 3);
    const v = Math.round(target * p);
    u.textContent = v + suf;
    if (p < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}
const io2 = new IntersectionObserver((es) => {
  es.forEach((e) => {
    if (e.isIntersecting) {
      if (!reduce) countUp(e.target);
      else { const u = e.target.querySelector(".u"); u.textContent = e.target.dataset.count + (e.target.dataset.suffix || ""); }
      io2.unobserve(e.target);
    }
  });
}, { threshold: 0.6 });
document.querySelectorAll(".n[data-count]").forEach((el) => io2.observe(el));
