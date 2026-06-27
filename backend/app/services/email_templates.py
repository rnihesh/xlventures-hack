"""Branded HTML/text builders for the emails Aperture sends.

Two kinds of mail:

* Verification: Aperture's transactional email to a new operator. Fully
  Aperture-branded (logo, wordmark, orange button).
* Outreach: the AI-drafted message an operator sends to an account's contacts.
  It is the operator's email to their own customer, so it stays clean and
  unbranded apart from a small "Sent via Aperture" footer.

All markup is table-based with inline styles so it renders across email
clients. The logo is served by the frontend at ``<app_base_url>/aperture-logo.png``.
No em dashes anywhere (project rule).
"""

from __future__ import annotations

from html import escape

from app.config import settings

# Palette (matches the app: grayscale plus the single orange accent).
_ORANGE = "#D97757"
_INK = "#1c1917"
_MUTED = "#57534e"
_FAINT = "#a8a29e"
_BORDER = "#e7e5e4"
_HAIRLINE = "#f0efed"
_CANVAS = "#f5f5f4"


def _logo_url() -> str:
    base = (settings.app_base_url or "https://aperture.niheshr.com").rstrip("/")
    return f"{base}/aperture-logo.png"


def verification_subject() -> str:
    return "Confirm your Aperture email"


def verification_text(link: str) -> str:
    return (
        "Welcome to Aperture.\n\n"
        "Confirm your email to start turning account signals into explainable, "
        "confidence-scored next best actions. Open the link below:\n"
        f"{link}\n\n"
        "If you did not create an Aperture account, you can ignore this message."
    )


def verification_html(link: str) -> str:
    safe = escape(link, quote=True)
    return f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_CANVAS};">
  <tr><td align="center" style="padding:40px 16px;">
    <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border:1px solid {_BORDER};border-radius:16px;">
      <tr><td style="padding:40px 40px 8px;" align="center">
        <img src="{_logo_url()}" width="48" height="48" alt="Aperture" style="display:block;border-radius:12px;">
      </td></tr>
      <tr><td style="padding:20px 40px 0;" align="center">
        <div style="font:600 13px/1 system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:{_FAINT};">Aperture</div>
        <h1 style="margin:10px 0 0;font:600 23px/1.3 -apple-system,system-ui,sans-serif;color:{_INK};">Confirm your email</h1>
      </td></tr>
      <tr><td style="padding:16px 40px 0;" align="center">
        <p style="margin:0;font:400 15px/1.6 -apple-system,system-ui,sans-serif;color:{_MUTED};">
          Welcome to Aperture. Confirm your email to start turning account signals into explainable, confidence-scored next best actions.
        </p>
      </td></tr>
      <tr><td style="padding:28px 40px 0;" align="center">
        <a href="{safe}" style="display:inline-block;background:{_ORANGE};color:#ffffff;font:600 15px/1 -apple-system,system-ui,sans-serif;text-decoration:none;padding:14px 32px;border-radius:10px;">Verify email</a>
      </td></tr>
      <tr><td style="padding:22px 40px 0;" align="center">
        <p style="margin:0;font:400 13px/1.6 system-ui,sans-serif;color:{_FAINT};">Button not working? Paste this link into your browser:</p>
        <p style="margin:6px 0 0;font:400 13px/1.5 ui-monospace,monospace;color:{_ORANGE};word-break:break-all;">{safe}</p>
      </td></tr>
      <tr><td style="padding:28px 40px 40px;">
        <div style="border-top:1px solid {_HAIRLINE};padding-top:18px;text-align:center;">
          <p style="margin:0;font:400 12px/1.5 system-ui,sans-serif;color:{_FAINT};">If you did not create an Aperture account, you can safely ignore this email.</p>
          <p style="margin:8px 0 0;font:600 12px/1.4 system-ui,sans-serif;color:{_MUTED};">Aperture &middot; Agentic decision intelligence</p>
        </div>
      </td></tr>
    </table>
  </td></tr>
</table>"""


def _paragraphs(body: str) -> str:
    """Turn a plain-text body into styled paragraphs (blank line splits)."""
    blocks = [b.strip() for b in body.replace("\r\n", "\n").split("\n\n") if b.strip()]
    if not blocks:
        blocks = [body.strip()]
    style = f"margin:0 0 16px;font:400 15px/1.7 -apple-system,system-ui,sans-serif;color:{_INK};"
    last = f"margin:0;font:400 15px/1.7 -apple-system,system-ui,sans-serif;color:{_INK};"
    out = []
    for i, block in enumerate(blocks):
        html = escape(block).replace("\n", "<br>")
        out.append(f'<p style="{last if i == len(blocks) - 1 else style}">{html}</p>')
    return "".join(out)


def outreach_html(body: str) -> str:
    """Clean, unbranded card around an outreach draft, small Aperture footer."""
    return f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_CANVAS};">
  <tr><td align="center" style="padding:40px 16px;">
    <table role="presentation" width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;background:#ffffff;border:1px solid {_BORDER};border-radius:16px;">
      <tr><td style="padding:36px 40px 0;">
        {_paragraphs(body)}
      </td></tr>
      <tr><td style="padding:24px 40px 36px;">
        <div style="border-top:1px solid {_HAIRLINE};padding-top:16px;">
          <table role="presentation" cellpadding="0" cellspacing="0"><tr>
            <td style="padding-right:6px;"><img src="{_logo_url()}" width="14" height="14" alt="" style="display:block;border-radius:4px;"></td>
            <td style="font:400 11px/1 system-ui,sans-serif;color:{_FAINT};">Sent via Aperture</td>
          </tr></table>
        </div>
      </td></tr>
    </table>
  </td></tr>
</table>"""
