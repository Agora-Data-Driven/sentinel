"""Content-versioned URLs for the CSS/JS the page shells load.

🔴 WHY THIS EXISTS, because the obvious reading is "we already solved caching" (2026-08-13).

`middleware.SecurityHeadersMiddleware` puts `Cache-Control: no-cache` on every non-API response.
That was the right fix for the 2026-07-27 incident (a day-old `dashboard.js` running against the new
`/api/dashboard`, rendering "undefined" KPIs) and it must not be undone — but "no-cache" means
*revalidate before every use*, not "don't store". So opening `/tasks` costs a conditional round trip
for `app.js` (65 kb), `taskboard.js` (215 kb) and `styles.css` (83 kb) plus every other shell asset,
**every single navigation**, forever. The bytes come back as cheap 304s; the LATENCY does not — and
`sw.js` is network-first, so its `fetch()` waits on those same round trips rather than hiding them.

A content-hashed URL removes the question instead of answering it faster. `/static/js/app.js?v=<hash>`
names one exact byte sequence, so it can be `immutable` for a year: the browser serves it from disk
with **no request at all**, and the service worker's network-first `fetch()` is satisfied from that
same HTTP cache. The staleness bug cannot come back, because a deploy that changes the file changes
the hash, which changes the URL — the old URL is simply never requested again.

Three properties this file is responsible for:

1. **The hash is over CONTENT, not mtimes.** A git checkout re-stamps every mtime, so an mtime-keyed
   id would change on every deploy and throw away caches that were still perfectly valid. Hashing the
   bytes means an unchanged `styles.css` keeps its URL — and stays cached in everyone's browser —
   across a deploy that only touched Python.
2. **An UNVERSIONED request still gets `no-cache`.** Anything we did not rewrite (the service worker's
   own precache list, a hand-written URL, an old bookmark) keeps exactly today's behaviour. The
   immutable header is granted only to a URL carrying the CURRENT build id, so a stale `?v=` can never
   pin the wrong bytes forever.
3. **Only `.js` and `.css` are rewritten.** They are the assets that are large, that change on a
   deploy, and that caused the incident. Images are already hand-versioned where it mattered
   (`logo.png?v=21`) and the regex deliberately skips any URL that already carries a query string.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

# Assets whose URL we rewrite. Keep this in step with `_ASSET_REF` below.
_VERSIONED_SUFFIXES = (".js", ".css")

# `src="/static/js/app.js"` / `href="/static/css/styles.css"`.
# `[^"?]+` is what makes a URL that ALREADY has a query string (logo.png?v=21) ineligible — appending
# a second `?v=` would produce a URL that 404s, and silently breaking one asset to speed up the rest
# is not a trade worth making.
_ASSET_REF = re.compile(
    rb'((?:src|href)=")(/static/[^"?]+\.(?:js|css))(")'
)


def _hash_static_assets(static_dir: Path) -> str:
    """Short sha256 over every versioned asset, in a stable order.

    Reads roughly 1 MB once at import. That is nothing next to the boot it happens during (Alembic,
    `create_all`, three seed/backfill passes) and `--cpu-boost` covers exactly this window.

    A missing/unreadable directory yields a constant id rather than raising: a frontend that failed to
    copy is a broken deploy, but it must not be a container that cannot boot at all — `check_dir=False`
    on the static mount makes the same call.
    """
    digest = hashlib.sha256()
    try:
        files = sorted(
            p for p in static_dir.rglob("*")
            if p.is_file() and p.suffix in _VERSIONED_SUFFIXES
        )
    except OSError:
        return "dev"
    for path in files:
        try:
            # The PATH is hashed too, so moving a file to a new name is a new build id even when the
            # bytes are identical.
            digest.update(str(path.relative_to(static_dir)).replace("\\", "/").encode("utf-8"))
            digest.update(path.read_bytes())
        except OSError:
            continue
    return digest.hexdigest()[:12] or "dev"


class Assets:
    """Build id + the HTML rewrite, bound to one frontend directory."""

    def __init__(self, frontend_dir: Path) -> None:
        self._pages_dir = frontend_dir / "pages"
        self.build_id = _hash_static_assets(frontend_dir / "static")
        self._suffix = b"?v=" + self.build_id.encode("ascii")
        # filename -> rewritten bytes. The shells are ~0.7 kb each and there are ~20 of them, so the
        # whole set is well under 20 kb held for the process lifetime.
        self._rendered: dict[str, bytes] = {}

    def rewrite(self, html: bytes) -> bytes:
        """Append `?v=<build id>` to every `/static/**.{js,css}` reference in a page shell."""
        return _ASSET_REF.sub(lambda m: m.group(1) + m.group(2) + self._suffix + m.group(3), html)

    def page(self, name: str) -> bytes:
        """The rewritten shell for `pages/<name>`, read from disk at most once.

        🔴 Memoized on purpose, and it is why `_page` no longer returns a `FileResponse`: the rewrite
        is pure (same file + same build id -> same bytes) and the build id is fixed for the life of
        the process, so re-reading and re-scanning the file per request would buy nothing. A page
        edited on a running server needs a restart — which is what `--reload` already does locally,
        and a production container never edits its own files.
        """
        hit = self._rendered.get(name)
        if hit is None:
            hit = self.rewrite((self._pages_dir / name).read_bytes())
            self._rendered[name] = hit
        return hit

    def is_current(self, query_string: bytes) -> bool:
        """Does this request's query name the build we are serving?

        Only then may the response be `immutable` — see property 2 in the module docstring. Parsed
        rather than substring-matched so `?v=<other>&x=v=<ours>` cannot sneak through.
        """
        from urllib.parse import parse_qs

        try:
            values = parse_qs(query_string.decode("latin-1")).get("v")
        except (UnicodeDecodeError, ValueError):
            return False
        return bool(values) and values[0] == self.build_id
