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
    headers: dict[str, str] | None = None,
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
    if headers:
        payload["headers"] = headers

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
    inviter_email: str | None = None,
    accept_url: str,
    is_existing_user: bool,
) -> bool:
    """Render and send the invite email.

    Copy is intentionally plain — no marketing pitch, no promotional
    language, no emoji — because Gmail and friends downrank exactly
    that kind of wording on a young domain. The subject names the
    inviter so it reads as a person-to-person notification, not a
    bulk-mail blast.
    """

    role_display = role.capitalize()
    who = inviter_name or "Someone"
    subject = f"{who} added you to {organization_name} on DocPilot"

    # Hidden Gmail "preview text" — the snippet shown next to the
    # subject in the inbox list. Plain and factual.
    pretext = f"{who} gave you {role_display} access on DocPilot. Open the link to sign in."

    html = f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{subject}</title>
  </head>
  <body style="margin:0;padding:0;background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1a1a1a;">
    <span style="display:none;color:#ffffff;font-size:1px;">{pretext}</span>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#ffffff;padding:24px 16px;">
      <tr><td align="center">
        <table role="presentation" width="540" cellspacing="0" cellpadding="0" border="0" style="max-width:540px;text-align:left;">
          <tr><td style="padding-bottom:24px;">
            <p style="font-size:14px;line-height:1.6;color:#1a1a1a;margin:0 0 16px;">Hi,</p>
            <p style="font-size:14px;line-height:1.6;color:#1a1a1a;margin:0 0 16px;">{who} added you to <strong>{organization_name}</strong> on DocPilot as a {role_display}.</p>
            <p style="font-size:14px;line-height:1.6;color:#1a1a1a;margin:0 0 24px;">Open the link below to sign in and start using it:</p>
            <p style="margin:0 0 24px;">
              <a href="{accept_url}" style="color:#1a73e8;text-decoration:underline;font-size:14px;">{accept_url}</a>
            </p>
            <p style="font-size:13px;line-height:1.6;color:#555555;margin:0 0 8px;">This link expires in 7 days. If you weren't expecting this email, you can ignore it.</p>
            <p style="font-size:13px;line-height:1.6;color:#555555;margin:0;">— DocPilot</p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>
"""

    text = (
        f"Hi,\n\n"
        f"{who} added you to {organization_name} on DocPilot as a {role_display}.\n\n"
        f"Open the link below to sign in and start using it:\n"
        f"{accept_url}\n\n"
        f"This link expires in 7 days. If you weren't expecting this email, you can ignore it.\n\n"
        f"— DocPilot"
    )

    # List-Unsubscribe is best practice even on transactional mail and
    # signals "real business" to Gmail / Outlook. We use mailto because
    # we don't run a one-click unsubscribe URL yet.
    extra_headers = {
        "List-Unsubscribe": "<mailto:support@usedocpilot.com>",
    }

    return send_email(
        to=to_email,
        subject=subject,
        html=html,
        text=text,
        reply_to=inviter_email,
        headers=extra_headers,
    )
