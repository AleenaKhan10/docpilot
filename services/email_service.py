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

    Branded layout: dark "▲ DocPilot" wordmark at the top, a big
    title, a white card with the message + a black CTA button, a
    fallback link, and a soft footer. Mirrors the GitHub /
    Linear style — a person-to-person notification rather than a
    marketing blast.
    """

    role_display = role.capitalize()
    who = inviter_name or "Someone"
    subject = f"{who} added you to {organization_name} on DocPilot"

    # Hidden preview text — the snippet shown next to the subject in
    # most email clients' inbox list.
    pretext = (
        f"{who} gave you {role_display} access on DocPilot. "
        f"This invitation expires in 7 days."
    )

    html = _render_branded_email(
        title=f"{who} added you to {organization_name}",
        pretext=pretext,
        body_html=f"""
        <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#1a1a1a;">Hi,</p>
        <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#1a1a1a;">
          <strong>{who}</strong> added you to
          <strong>{organization_name}</strong> on DocPilot as a
          <strong>{role_display}</strong>.
        </p>
        <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#1a1a1a;">
          Click the button below to sign in and open the workspace.
        </p>
        <p style="margin:0 0 24px;font-size:13px;line-height:1.6;color:#666666;text-align:center;">
          This invitation expires in 7 days.
        </p>
        """,
        cta_label="Accept invitation",
        cta_url=accept_url,
        fallback_url=accept_url,
        footer_html=(
            f"You're receiving this email because <strong>{who}</strong> "
            f"added you to <strong>{organization_name}</strong> on DocPilot. "
            f"If you weren't expecting this, you can safely ignore the email."
        ),
    )

    text = (
        f"Hi,\n\n"
        f"{who} added you to {organization_name} on DocPilot as a {role_display}.\n\n"
        f"Accept the invitation here:\n{accept_url}\n\n"
        f"This invitation expires in 7 days. If you weren't expecting this email, "
        f"you can safely ignore it.\n\n"
        f"— DocPilot"
    )

    # List-Unsubscribe is best practice even on transactional mail and
    # signals "real business" to Gmail / Outlook.
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


def _render_branded_email(
    *,
    title: str,
    pretext: str,
    body_html: str,
    cta_label: str,
    cta_url: str,
    fallback_url: str,
    footer_html: str,
) -> str:
    """Shared HTML shell for branded transactional emails.

    Layout: wordmark header → title → white card with body + CTA →
    "button not working" fallback link → muted footer. All inline
    styles (Gmail/Outlook strip <style> blocks). Single column,
    540px max, renders on mobile.
    """
    return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="color-scheme" content="light" />
    <meta name="supported-color-schemes" content="light" />
    <title>{title}</title>
  </head>
  <body style="margin:0;padding:0;background-color:#f6f7f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Ubuntu,'Helvetica Neue',sans-serif;color:#1a1a1a;-webkit-font-smoothing:antialiased;">
    <span style="display:none !important;visibility:hidden;opacity:0;color:transparent;height:0;width:0;overflow:hidden;font-size:1px;line-height:1px;">{pretext}</span>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background-color:#f6f7f9;padding:40px 16px;">
      <tr>
        <td align="center">

          <!-- Wordmark: real logo PNG + name in a dark pill -->
          <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:0 auto 28px;">
            <tr>
              <td style="background-color:#0b0b0c;padding:10px 18px;border-radius:10px;line-height:1;">
                <img src="https://app.usedocpilot.com/logo-white.png" alt="" width="16" height="16" style="display:inline-block;vertical-align:middle;border:0;outline:none;text-decoration:none;" />
                <span style="display:inline-block;vertical-align:middle;margin-left:8px;color:#ffffff;font-size:15px;font-weight:700;letter-spacing:-0.01em;line-height:1;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">DocPilot</span>
              </td>
            </tr>
          </table>

          <!-- Title -->
          <h1 style="margin:0 0 28px;font-size:22px;font-weight:600;color:#0b0b0c;text-align:center;line-height:1.3;max-width:520px;">
            {title}
          </h1>

          <!-- Card -->
          <table role="presentation" width="540" cellspacing="0" cellpadding="0" border="0" style="max-width:540px;background-color:#ffffff;border-radius:14px;border:1px solid #e6e8eb;box-shadow:0 1px 2px rgba(15,18,22,0.04);">
            <tr>
              <td style="padding:32px;">
                {body_html}

                <!-- CTA button (table-based for Outlook compat) -->
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:0 auto;">
                  <tr>
                    <td align="center" bgcolor="#0b0b0c" style="background-color:#0b0b0c;border-radius:10px;">
                      <a href="{cta_url}" style="display:inline-block;padding:13px 28px;font-size:15px;font-weight:600;color:#ffffff;text-decoration:none;border-radius:10px;line-height:1;">
                        {cta_label}
                      </a>
                    </td>
                  </tr>
                </table>

                <p style="margin:32px 0 6px;font-size:12px;line-height:1.6;color:#7a7f88;">
                  Button not working? Paste the following link into your browser:
                </p>
                <p style="margin:0;font-size:12px;line-height:1.6;color:#555;word-break:break-all;">
                  <a href="{fallback_url}" style="color:#555;text-decoration:underline;">{fallback_url}</a>
                </p>
              </td>
            </tr>
          </table>

          <!-- Footer -->
          <p style="margin:24px auto 0;max-width:540px;font-size:12px;line-height:1.6;color:#8a9099;text-align:center;">
            {footer_html}
          </p>
          <p style="margin:8px auto 0;max-width:540px;font-size:11px;line-height:1.5;color:#a0a4ad;text-align:center;">
            DocPilot &middot; <a href="https://usedocpilot.com" style="color:#a0a4ad;text-decoration:none;">usedocpilot.com</a>
          </p>

        </td>
      </tr>
    </table>
  </body>
</html>
"""
