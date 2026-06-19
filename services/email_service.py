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


ROLE_DESCRIPTIONS = {
    "owner": "Manage everything in the workspace — billing, members, and every document.",
    "admin": "View every document in the workspace and manage teammates. Admins cannot delete documents that aren't theirs.",
    "member": "Create new documents from screen recordings. Access shared documents with the level (view or edit) you were granted on each.",
    "guest": "Access documents shared with you, with the level (view or edit) you were granted on each. Cannot create new documents.",
}


def send_invite_email(
    *,
    to_email: str,
    organization_name: str,
    role: str,
    inviter_name: str | None,
    inviter_email: str | None = None,
    accept_url: str,
    is_existing_user: bool,
    expires_at=None,
) -> bool:
    """Render and send the invite email.

    GitHub-style detailed layout: wordmark, big title, recipient card
    with role description, expiry date, sign-in hint, CTA, fallback
    link, and a help section. Everything that helps the recipient
    understand who, what, and how to act.
    """

    role_display = role.capitalize()
    who = inviter_name or "Someone"
    inviter_display = (
        f"{who} ({inviter_email})" if inviter_email and inviter_name else who
    )
    subject = f"{who} added you to {organization_name} on DocPilot"

    role_blurb = ROLE_DESCRIPTIONS.get(role.lower(), "")

    if expires_at:
        # Format like "27 June 2026 (UTC)" — readable and unambiguous.
        try:
            expires_str = expires_at.strftime("%-d %B %Y (UTC)")
        except ValueError:
            # %-d is GNU-only; Windows fallback.
            expires_str = expires_at.strftime("%d %B %Y (UTC)").lstrip("0")
    else:
        expires_str = "7 days from now"

    pretext = (
        f"{who} added you to {organization_name} on DocPilot as a "
        f"{role_display}. Accept by {expires_str}."
    )

    role_block = f"""
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
        style="margin:8px 0 24px;background-color:#f6f7f9;border:1px solid #e6e8eb;border-radius:10px;">
        <tr><td style="padding:14px 16px;">
          <p style="margin:0 0 4px;font-size:11px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:#7a7f88;">
            Your role
          </p>
          <p style="margin:0 0 6px;font-size:14px;font-weight:600;color:#0b0b0c;">{role_display}</p>
          <p style="margin:0;font-size:13px;line-height:1.55;color:#3d4148;">{role_blurb}</p>
        </td></tr>
      </table>
    """

    invite_facts_block = f"""
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
        style="margin:0 0 24px;background-color:#fbfbfc;border:1px solid #eef0f3;border-radius:10px;">
        <tr><td style="padding:14px 16px;font-size:13px;line-height:1.6;color:#3d4148;">
          <div><strong style="color:#0b0b0c;">Workspace:</strong> {organization_name}</div>
          <div><strong style="color:#0b0b0c;">Invited by:</strong> {inviter_display}</div>
          <div><strong style="color:#0b0b0c;">Sign-in email:</strong> {to_email}</div>
          <div><strong style="color:#0b0b0c;">Invitation expires:</strong> {expires_str}</div>
        </td></tr>
      </table>
    """

    body_html = f"""
      <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#1a1a1a;">Hi,</p>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#1a1a1a;">
        <strong>{who}</strong> added you to
        <strong>{organization_name}</strong> on DocPilot as a
        <strong>{role_display}</strong>.
      </p>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#1a1a1a;">
        DocPilot turns screen recordings into structured docs — SOPs, training
        guides, and handovers — automatically.
      </p>

      {invite_facts_block}
      {role_block}

      <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#1a1a1a;">
        Click the button below to accept and open the workspace.
      </p>
    """

    help_block = f"""
      <hr style="margin:32px 0 20px;border:none;border-top:1px solid #eef0f3;" />
      <p style="margin:0 0 6px;font-size:11px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:#7a7f88;">
        Need help?
      </p>
      <ul style="margin:0 0 0 18px;padding:0;font-size:13px;line-height:1.7;color:#3d4148;">
        <li>If you get a 404 page, make sure you're signed in as <strong>{to_email}</strong>.</li>
        <li>You can also go to <a href="https://app.usedocpilot.com" style="color:#3d4148;text-decoration:underline;">https://app.usedocpilot.com</a> and sign in directly.</li>
        <li>If you don't know <strong>{who}</strong>, reply to this email — it goes straight to them — or just ignore this message.</li>
      </ul>
    """

    html = _render_branded_email(
        title=f"{who} added you to {organization_name}",
        pretext=pretext,
        body_html=body_html + help_block,
        cta_label=f"Accept invitation to {organization_name}",
        cta_url=accept_url,
        fallback_url=accept_url,
        footer_html=(
            f"You're receiving this email because <strong>{who}</strong> "
            f"({inviter_email or 'no email on file'}) added <strong>{to_email}</strong> to "
            f"<strong>{organization_name}</strong> on DocPilot. "
            f"You will not be added to the workspace unless you click the button above."
        ),
        footer_links_html=(
            '<a href="https://app.usedocpilot.com/login" style="color:#7a7f88;text-decoration:underline;">Sign in</a>'
            ' &middot; '
            '<a href="https://usedocpilot.com" style="color:#7a7f88;text-decoration:underline;">About DocPilot</a>'
            ' &middot; '
            '<a href="mailto:support@usedocpilot.com" style="color:#7a7f88;text-decoration:underline;">Report abuse</a>'
        ),
    )

    text = (
        f"Hi,\n\n"
        f"{who} added you to {organization_name} on DocPilot as a {role_display}.\n\n"
        f"What this role can do:\n"
        f"  {role_blurb}\n\n"
        f"Workspace:         {organization_name}\n"
        f"Invited by:        {inviter_display}\n"
        f"Sign-in email:     {to_email}\n"
        f"Invitation expires: {expires_str}\n\n"
        f"Accept the invitation here:\n{accept_url}\n\n"
        f"Need help?\n"
        f"  - If you get a 404, make sure you're signed in as {to_email}.\n"
        f"  - You can also go to https://app.usedocpilot.com and sign in directly.\n"
        f"  - If you don't know {who}, reply to this email — it goes to them — or ignore this message.\n\n"
        f"You will not be added to the workspace unless you click the link.\n\n"
        f"— DocPilot · https://usedocpilot.com"
    )

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
    footer_links_html: str | None = None,
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
          {('<p style="margin:12px auto 0;max-width:540px;font-size:11px;line-height:1.6;color:#7a7f88;text-align:center;">' + footer_links_html + '</p>') if footer_links_html else ''}
          <p style="margin:8px auto 0;max-width:540px;font-size:11px;line-height:1.5;color:#a0a4ad;text-align:center;">
            DocPilot &middot; <a href="https://usedocpilot.com" style="color:#a0a4ad;text-decoration:none;">usedocpilot.com</a>
          </p>

        </td>
      </tr>
    </table>
  </body>
</html>
"""
