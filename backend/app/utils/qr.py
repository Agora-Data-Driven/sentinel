"""QR code generation for employee attendance badges.

Each active employee has a ``qr_tokens`` row; the kiosk camera reads the token string and the
backend maps it back to the user. ``make_qr_png`` renders that token as a scannable PNG.

🟡 **KNOWN WEAKNESS — the badge token is a STATIC, NON-EXPIRING BEARER SECRET.** Raised 2026-08-14,
documented rather than changed, because every fix is an operational decision about physical badges
that somebody has to choose (and re-print for). Stating it plainly so it is not re-discovered as a
surprise:

``new_token`` mints one random string per employee, ``attendance._resolve_token`` accepts it forever
(it checks only ``is_active``), and the punch endpoints trust whoever presents it. So **a photograph
of a colleague's badge is a permanent ability to clock that colleague in, from any device,
anywhere** — there is no rotation, no expiry, no device binding, no geofence and no rate limit.
``attendance.kiosk_guard`` also accepts the kiosk key as a **query parameter**
(``?kiosk_key=``), which lands in access logs and browser history, and it is fully open in
development when no key is set.

🔴 **The full write-up is [`docs/KIOSK_SECURITY_DRAFT.md`](../../../docs/KIOSK_SECURITY_DRAFT.md)** —
options, the constraints any fix must respect (the kiosk boots OFFLINE; punches queue in IndexedDB
and sync later), and the open questions. Read it before starting; it is a DRAFT, nothing is built.

Ordered by effort, each independently deployable:

1. **Rotate on demand** — a "reissue badge" action that mints a new token and invalidates the old
   one, so a leaked badge has a remedy at all. Cheapest, and today there is none.
2. **Bind the punch to the device** — require the kiosk key *and* the badge, and move the key to the
   header only, so a stolen badge alone is inert off the kiosk tablet.
3. **Make the code time-based** (TOTP-style, badge carries the seed) so a photograph expires. 🔴 This
   one changes what is PRINTED on the badge: a static PNG can no longer be the credential, so it
   needs a screen or a re-issued badge per person. Do not start here by accident.
"""
from __future__ import annotations

import io
import secrets

import qrcode


def new_token() -> str:
    """A URL-safe random token for a new QR badge."""
    return secrets.token_urlsafe(18)


def make_qr_png(data: str, box_size: int = 10, border: int = 3) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    # Agora graphite on white — matches the badge print aesthetic.
    img = qr.make_image(fill_color="#1A1B1E", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
