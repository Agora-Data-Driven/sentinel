"""Retrieval over a worker's imported mentor transcripts — the thing that lets the AI coach
actually ANSWER "what would Nick say about my plan?" or mentor them in Nick's voice.

WHY RETRIEVAL AND NOT JUST A BIGGER PROMPT: the Mentor Library is enormous. One creator alone
(Nick Saraev) runs to ~104 transcripts / ~1M words; the holistic digest could therefore only ever
list TITLES, which is why the coach knew these mentors existed but had never read a word of them.
Dumping is impossible and truncating is arbitrary, so we search: pull the handful of passages that
actually bear on the question and hand only those to the model.

The approach mirrors Atrium's assistant (`dash/assistant_ai.py`) — pure-Python BM25 over chunks,
NO new dependency, NO new table, NO migration (Sentinel's prod has a history of not running
Alembic, so a schema change here would be a silent no-op in production). Everything is derived
from the existing `mentor_transcripts` rows and cached in-process.

Two deliberate details carried over from Atrium's hard-won experience:
  * Chunks are indexed by TITLE + body. A transcript's body rarely says its own mentor's name, so
    without this "what does Nick say about cold email" retrieves nothing from Nick.
  * Scoring is BM25, not raw term counts: long transcripts would otherwise dominate purely by
    being long.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import MentorTranscript

# --- tuning ------------------------------------------------------------------
CHUNK_WORDS = 220           # ~a paragraph of speech; big enough to carry an argument
CHUNK_OVERLAP = 40          # so a point split across a boundary is still findable whole
MAX_CHUNKS = 24_000         # safety rail on memory for one user's index
K1 = 1.5                    # BM25 term-frequency saturation
B = 0.75                    # BM25 length normalisation
DEFAULT_LIMIT = 8

# Deliberately tiny: an aggressive stopword list would strip the very words that make a mentor
# question specific ("how", "should", "when"). These carry no retrieval signal at all.
_STOP = frozenset("""
a an and are as at be been but by for from had has have i if in into is it its of on or s t that
the their then there these they this to was were what which who will with you your
""".split())

_WORD = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, stopwords and 1-char noise dropped."""
    return [w for w in _WORD.findall((text or "").lower()) if len(w) > 1 and w not in _STOP]


def _chunk_words(words: list[str]) -> list[str]:
    """Overlapping windows of `CHUNK_WORDS`. Overlap is what keeps an idea that straddles a
    boundary retrievable as one passage instead of two half-thoughts."""
    if not words:
        return []
    step = max(1, CHUNK_WORDS - CHUNK_OVERLAP)
    out = []
    for start in range(0, len(words), step):
        window = words[start:start + CHUNK_WORDS]
        if not window:
            break
        out.append(" ".join(window))
        if start + CHUNK_WORDS >= len(words):
            break
    return out


class _Index:
    """One user's searchable corpus. Built once, then reused until their library changes."""

    __slots__ = ("chunks", "tfs", "lengths", "idf", "avg_len")

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.tfs: list[Counter] = []
        self.lengths: list[int] = []
        df: Counter = Counter()
        for c in chunks:
            # Title + mentor + body: the entity name a question searches by is almost never
            # spoken inside the transcript itself.
            toks = tokenize("%s %s %s" % (c["mentor"], c["title"], c["text"]))
            tf = Counter(toks)
            self.tfs.append(tf)
            self.lengths.append(len(toks) or 1)
            df.update(tf.keys())
        n = len(chunks) or 1
        self.avg_len = (sum(self.lengths) / n) if self.lengths else 1.0
        self.idf = {
            term: math.log(1.0 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }

    def score(self, terms: list[str], keep: set[int] | None) -> list[tuple[float, int]]:
        """BM25 over the (optionally mentor-filtered) chunk set. Highest first."""
        hits: list[tuple[float, int]] = []
        for i, tf in enumerate(self.tfs):
            if keep is not None and i not in keep:
                continue
            total = 0.0
            norm = K1 * (1 - B + B * (self.lengths[i] / (self.avg_len or 1.0)))
            for term in terms:
                f = tf.get(term)
                if not f:
                    continue
                total += self.idf.get(term, 0.0) * (f * (K1 + 1)) / (f + norm)
            if total > 0:
                hits.append((total, i))
        hits.sort(key=lambda h: (-h[0], h[1]))
        return hits


# Cache one index per user. Rebuilding tokenises megabytes (~1-2 s for a big library), so doing it
# per chat turn would be felt; the signature below makes a stale index impossible.
_CACHE: dict[int, tuple[tuple, _Index]] = {}
_LOCK = threading.Lock()


def _signature(db: Session, user_id: int) -> tuple:
    """Cheap fingerprint of the user's library — changes on any add or delete."""
    row = db.execute(
        select(func.count(MentorTranscript.id), func.max(MentorTranscript.id),
               func.sum(func.length(MentorTranscript.transcript_text)))
        .where(MentorTranscript.user_id == user_id)
    ).one()
    return (row[0] or 0, row[1] or 0, row[2] or 0)


def _build(db: Session, user_id: int) -> _Index:
    rows = db.execute(
        select(MentorTranscript).where(MentorTranscript.user_id == user_id)
        .order_by(MentorTranscript.id)
    ).scalars().all()
    chunks: list[dict] = []
    for t in rows:
        for ordinal, text in enumerate(_chunk_words((t.transcript_text or "").split())):
            chunks.append({
                "mentor": t.mentor_name or "",
                "title": t.title or "",
                "url": t.source_url or "",
                "text": text,
                "ordinal": ordinal,
                "transcript_id": t.id,
            })
            if len(chunks) >= MAX_CHUNKS:
                break
        if len(chunks) >= MAX_CHUNKS:
            break
    return _Index(chunks)


def _index_for(db: Session, user_id: int) -> _Index:
    sig = _signature(db, user_id)
    with _LOCK:
        cached = _CACHE.get(user_id)
        if cached and cached[0] == sig:
            return cached[1]
    index = _build(db, user_id)          # built outside the lock: it's the slow part
    with _LOCK:
        _CACHE[user_id] = (sig, index)
    return index


def roster(db: Session, user_id: int) -> list[dict]:
    """Who this worker can be coached BY, biggest library first.

    The coach needs to know which mentors it can legitimately channel — and equally, which it
    cannot, so it never invents a position for someone it has nothing from."""
    rows = db.execute(
        select(MentorTranscript.mentor_name, func.count(MentorTranscript.id))
        .where(MentorTranscript.user_id == user_id)
        .group_by(MentorTranscript.mentor_name)
        .order_by(func.count(MentorTranscript.id).desc())
    ).all()
    return [{"name": name or "Unknown", "transcripts": int(count or 0)}
            for name, count in rows if (count or 0) > 0]


def resolve_mentor(db: Session, user_id: int, name: str) -> str:
    """Match a loosely-typed mentor name ("nick", "saraev") to the stored one. "" if no match.

    People ask for "Nick", not "Nick Saraev", so an exact-match-only filter would silently return
    nothing and the coach would answer ungrounded — the worst failure mode here."""
    want = (name or "").strip().lower()
    if not want:
        return ""
    names = [r["name"] for r in roster(db, user_id)]
    for n in names:                                   # exact, then containment either way
        if n.lower() == want:
            return n
    for n in names:
        if want in n.lower() or n.lower() in want:
            return n
    want_parts = set(want.split())
    for n in names:                                   # any shared name part ("saraev")
        if want_parts & set(n.lower().split()):
            return n
    return ""


def search(db: Session, user_id: int, query: str, mentor: str = "",
           limit: int = DEFAULT_LIMIT) -> dict:
    """The passages from this worker's mentor library that bear on `query`.

    `mentor` narrows to one mentor (fuzzily resolved). Returns the excerpts plus the resolved
    mentor name so the caller can tell "Nick said nothing about this" from "no such mentor"."""
    terms = tokenize(query)
    resolved = resolve_mentor(db, user_id, mentor) if mentor else ""
    if mentor and not resolved:
        return {"mentor": "", "matched_mentor": False, "excerpts": []}
    if not terms:
        return {"mentor": resolved, "matched_mentor": bool(resolved), "excerpts": []}

    index = _index_for(db, user_id)
    if not index.chunks:
        return {"mentor": resolved, "matched_mentor": bool(resolved), "excerpts": []}

    keep = None
    if resolved:
        keep = {i for i, c in enumerate(index.chunks) if c["mentor"] == resolved}
        if not keep:
            return {"mentor": resolved, "matched_mentor": True, "excerpts": []}

    excerpts = []
    seen_per_transcript: Counter = Counter()
    for score, i in index.score(terms, keep):
        c = index.chunks[i]
        # Spread the answer across a mentor's material: without this a single long transcript can
        # fill every slot and the coach sees one video's opinion as if it were the whole mentor.
        if seen_per_transcript[c["transcript_id"]] >= 2:
            continue
        seen_per_transcript[c["transcript_id"]] += 1
        excerpts.append({"mentor": c["mentor"], "title": c["title"], "url": c["url"],
                         "text": c["text"], "score": round(score, 3)})
        if len(excerpts) >= max(1, min(limit, 20)):
            break
    return {"mentor": resolved, "matched_mentor": bool(resolved), "excerpts": excerpts}
