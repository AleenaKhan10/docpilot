"""
Resend wrapper for transactional emails.

We send invites (and any future transactional email) via Resend's REST API
directly — no SDK, just httpx — to keep the dependency surface small.

Configuration: RESEND_API_KEY + RESEND_FROM in the env.

`send_email` is the low-level primitive. `send_invite_email` is what
routes/invitations.py calls; if a templated email ever needs to change
shape, change it here, not at the call site.
"""

import os
import logging
import httpx

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_TIMEOUT_S = 8.0


def _api_key() -> str | None:
    return (os.getenv("RESEND_API_KEY") or "").strip() or None


def _from_address() -> str:
    return os.getenv("RESEND_FROM", "DocPilot <noreply@usedocpilot.com>").strip()


def send_email(
    *,
    to: str | list[str],
    subject: str,
    html: str,
    text: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """Send a single email through Resend. Returns True on 2xx.

    Failure modes are logged but never raised — email is best-effort and
    must not block the calling request.
    """
    key = _api_key()
    if not key:
        logger.warning("RESEND_API_KEY not set — skipping email send (to=%s, subject=%r)", to, subject)
        return False

    payload: dict = {
        "from": _from_address(),
        "to": to if isinstance(to, list) else [to],
        "subject": subject,
        "html": html,
    }
    if text:
        payload["text"] = text
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        r = httpx.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=DEFAULT_TIMEOUT_S,
        )
    except httpx.HTTPError as e:
        logger.warning("Resend network error sending to %s: %s", to, e)
        return False

    if 200 <= r.status_code < 300:
        return True
    logger.warning("Resend rejected email to %s (%s): %s", to, r.status_code, r.text[:300])
    return False


def send_invite_email(
    *,
    to_email: str,
    organization_name: str,
    role: str,
    inviter_name: str | None,
    accept_url: str,
    is_existing_user: bool,
) -> bool:
    """Render and send the invite email."""

    role_display = role.capitalize()
    inviter_line = (
        f"<strong>{inviter_name}</strong> invited you"
        if inviter_name
        else "You've been invited"
    )
    cta_label = "Accept invitation"
    pretext = (
        f"Join {organization_name} on DocPilot as {role_display.lower()}."
        if not is_existing_user
        else f"Accept your role of {role_display.lower()} in {organization_name}."
    )

    html = f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>You're invited to {organization_name} on DocPilot</title>
  </head>
  <body style="margin:0;padding:0;background:#0b0b0c;font-family:'DM Sans',-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;color:#e6e6e6;">
    <span style="display:none;color:#0b0b0c;">{pretext}</span>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#0b0b0c;padding:32px 16px;">
      <tr><td align="center">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0" border="0" style="max-width:560px;background:#141416;border:1px solid #26262a;border-radius:12px;padding:32px;">
          <tr><td>
            <div style="font-size:18px;font-weight:600;letter-spacing:-0.01em;color:#fafafa;margin-bottom:24px;">DocPilot</div>
            <h1 style="font-size:22px;font-weight:600;line-height:1.3;color:#fafafa;margin:0 0 16px;">You're invited to join {organization_name}</h1>
            <p style="font-size:15px;line-height:1.6;color:#b3b3b3;margin:0 0 24px;">{inviter_line} to <strong style="color:#fafafa;">{organization_name}</strong> on DocPilot as <strong style="color:#fafafa;">{role_display}</strong>.</p>
            <p style="font-size:15px;line-height:1.6;color:#b3b3b3;margin:0 0 32px;">DocPilot turns screen recordings into structured documentation — SOPs, training guides, handovers — automatically.</p>
            <div style="margin:0 0 32px;">
              <a href="{accept_url}" style="display:inline-block;background:#fafafa;color:#0b0b0c;font-weight:600;font-size:15px;padding:12px 24px;border-radius:8px;text-decoration:none;">{cta_label}</a>
            </div>
            <p style="font-size:13px;line-height:1.6;color:#7a7a7a;margin:0 0 8px;">If the button doesn't work, paste this into your browser:</p>
            <p style="font-size:13px;line-height:1.6;color:#9a9a9a;margin:0 0 32px;word-break:break-all;"><a href="{accept_url}" style="color:#9a9a9a;text-decoration:underline;">{accept_url}</a></p>
            <hr style="border:none;border-top:1px solid #26262a;margin:0 0 24px;" />
            <p style="font-size:12px;line-height:1.6;color:#666;margin:0;">This invitation expires in 7 days. If you didn't expect it, you can safely ignore this email.</p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>
"""

    text = (
        f"{inviter_line.replace('<strong>', '').replace('</strong>', '')} to {organization_name} on DocPilot as {role_display}.\n\n"
        f"Accept the invitation: {accept_url}\n\n"
        f"This invitation expires in 7 days. If you didn't expect it, you can ignore this email."
    )

    return send_email(
        to=to_email,
        subject=f"You're invited to {organization_name} on DocPilot",
        html=html,
        text=text,
    )
