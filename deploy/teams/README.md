# Audit_bot as a Microsoft Teams app (static tab)

Two Teams apps, both plain web tabs pointing at the Audit_bot server -- no bot, no Azure AD app
registration, no Graph permissions:

| Package                 | Opens     | Intended for         |
|-------------------------|-----------|----------------------|
| `audit-bot-field.zip`   | `/app/`   | all field engineers  |
| `audit-bot-admin.zip`   | `/admin/` | admins only          |

## Build

```
python deploy/teams/build_teams_package.py --base-url https://<audit-bot-server> --version 1.0.0
```

Output: `deploy/teams/dist/*.zip`. Re-upload after changing the URL with the same app id and a
higher `--version`.

## Server requirements

- Reachable over **HTTPS** with a certificate trusted on users' machines (Teams refuses http and
  self-signed certs). An internal hostname only works for users on the company network/VPN.
- The server sends `Content-Security-Policy: frame-ancestors 'self' <Teams hosts>` (see
  `AUDIT_BOT_FRAME_ANCESTORS` in `server/.env.example`). Nothing in front of it (nginx, WAF,
  proxy) may add `X-Frame-Options`.

## What to ask IT (Teams admin)

1. Upload both zips in **Teams admin center > Teams apps > Manage apps > Upload new app**
   (org-wide custom app), or allow us to upload custom apps ("Upload custom apps" in the app
   setup policy) so we can test first.
2. **Permission policy**: allow the Field app for the field engineers group, the Admin app only
   for the admins group.
3. Optional **setup policy**: pin the Field app in the Teams app bar for the field group.
4. Confirm the server hostname is allowed by any proxy/Conditional Access rules for the Teams
   desktop and mobile clients, and that browser policy doesn't block third-party storage for it
   (Edge/Chrome `BlockThirdPartyCookies`; if set, add the server to `CookiesAllowedForUrls`).
