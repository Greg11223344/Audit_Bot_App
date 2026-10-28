"""Builds the Microsoft Teams app packages (static personal tab) for the field app and the admin app.

Usage (from the repo root; needs Pillow -- `pip install pillow`):

    python deploy/teams/build_teams_package.py --base-url https://audit.company.local

Writes deploy/teams/dist/audit-bot-field.zip and audit-bot-admin.zip. Each zip holds
manifest.json + color.png (192x192) + outline.png (32x32, white on transparent) at its root, which
is exactly what Teams Admin Center / "Upload a custom app" expects.

Two separate apps rather than one app with two tabs, so IT can make the Admin app available only to
admins (app permission policy) while every field engineer gets the Field app.

The app ids below are fixed on purpose: Teams treats a package with the same id + a higher
--version as an update of the already-uploaded app. Bump --version on every re-upload.
"""
import argparse
import io
import json
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

REPO_DIR = Path(__file__).resolve().parents[2]
DIST_DIR = Path(__file__).resolve().parent / "dist"

APPS = {
    "field": {
        "id": "6f1d2c4e-8a3b-4b7e-9c51-2e7a0d4f9b13",
        "path": "/app/",
        "icon": REPO_DIR / "field-app" / "icons" / "icon-512.png",
        "accent": "#2F3E46",
        "short_name": "Audit_bot",
        "full_name": "Audit_bot - Field Audit",
        "tab_name": "Field Audit",
        "short_desc": "Field audit checklists for service engineers.",
        "full_desc": (
            "Audit_bot field app: fill in audit checklists on customer machines, attach photos and "
            "submit them for review. Opens the same web app as /app/ on the Audit_bot server."
        ),
    },
    "admin": {
        "id": "b3e8f0a2-5d71-4c9a-a6e4-7f2c1b8d0e56",
        "path": "/admin/",
        "icon": REPO_DIR / "admin-app" / "icons" / "icon-512.png",
        "accent": "#52796F",
        "short_name": "Audit_bot Admin",
        "full_name": "Audit_bot - Admin Dashboard",
        "tab_name": "Admin",
        "short_desc": "Audit_bot admin dashboard: audits, tasks, users and reports.",
        "full_desc": (
            "Audit_bot admin dashboard: review submitted audits, manage tasks, users and the "
            "machine catalog, and download PDF reports. Opens the same web app as /admin/ on the "
            "Audit_bot server."
        ),
    },
}


def color_icon(src: Path) -> bytes:
    img = Image.open(src).convert("RGB").resize((192, 192), Image.LANCZOS)
    return _png(img)


def outline_icon(src: Path) -> bytes:
    # Teams requires the outline icon to be pure white on a transparent background. The source
    # icons are white letters on a solid colour, so the white pixels become the outline's alpha.
    img = Image.open(src).convert("L")
    mask = img.point(lambda v: 255 if v > 200 else 0)
    mask = mask.crop(mask.getbbox())
    mask.thumbnail((28, 28), Image.LANCZOS)  # 2px transparent margin inside 32x32
    out = Image.new("RGBA", (32, 32), (255, 255, 255, 0))
    glyph = Image.new("RGBA", mask.size, (255, 255, 255, 255))
    glyph.putalpha(mask)
    out.paste(glyph, ((32 - mask.width) // 2, (32 - mask.height) // 2), glyph)
    return _png(out)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def manifest(app: dict, base_url: str, version: str, developer: str) -> dict:
    host = urlparse(base_url).hostname
    url = base_url + app["path"]
    return {
        "$schema": "https://developer.microsoft.com/en-us/json-schemas/teams/v1.17/MicrosoftTeams.schema.json",
        "manifestVersion": "1.17",
        "version": version,
        "id": app["id"],
        "developer": {
            "name": developer,
            "websiteUrl": base_url + "/",
            "privacyUrl": url,
            "termsOfUseUrl": url,
        },
        "name": {"short": app["short_name"], "full": app["full_name"]},
        "description": {"short": app["short_desc"], "full": app["full_desc"]},
        "icons": {"color": "color.png", "outline": "outline.png"},
        "accentColor": app["accent"],
        "staticTabs": [
            {
                "entityId": "main",
                "name": app["tab_name"],
                "contentUrl": url,
                "websiteUrl": url,  # "Open in browser" button in the tab header
                "scopes": ["personal"],
            }
        ],
        # Camera for the field app's photo capture (<input capture>) on Teams mobile.
        "devicePermissions": ["media"],
        "validDomains": [host],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="Public HTTPS address of the Audit_bot server, e.g. https://audit.company.local")
    parser.add_argument("--version", default="1.0.0", help="App version (x.y.z); bump on every re-upload")
    parser.add_argument("--developer", default="Audit_bot", help="Developer/company name shown in the Teams store page")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    if urlparse(base_url).scheme != "https" or not urlparse(base_url).hostname:
        parser.error("--base-url must be a full https:// address (Teams refuses http tabs)")

    DIST_DIR.mkdir(exist_ok=True)
    for key, app in APPS.items():
        out = DIST_DIR / f"audit-bot-{key}.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest(app, base_url, args.version, args.developer), indent=2, ensure_ascii=False))
            zf.writestr("color.png", color_icon(app["icon"]))
            zf.writestr("outline.png", outline_icon(app["icon"]))
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
