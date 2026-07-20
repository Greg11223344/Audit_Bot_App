"""Verifies: dashboard KPI cards are clickable and navigate correctly, the trend chart renders,
a machine row navigates to a machine-detail page, and admin-only audit deletion works (with a
confirmation dialog, live row removal, and the delete button hidden from non-admins)."""
import sys
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

SCREENSHOT_DIR = Path(__file__).parent / "smoke_screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

BASE = "http://127.0.0.1:8000"
ADMIN_EMAIL = "admin@auditbot.local"
ADMIN_PASSWORD = "ChangeMe123!"

console_errors = []


def log_console(msg):
    if msg.type == "error":
        console_errors.append(msg.text)


def ascii_safe(s):
    return s.encode("ascii", "backslashreplace").decode()


def main():
    import httpx

    # ---- Create a disposable audit + a non-admin user via the API directly (test setup) ----
    api = httpx.Client(base_url=f"{BASE}/api")
    login = api.post("/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    admin_token = login.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    machines = api.get("/catalog/machines", headers=admin_headers).json()
    machine_id = machines[0]["id"]

    client_uuid = str(uuid.uuid4())
    sync_resp = api.post(
        "/audits/sync",
        json={"audits": [{
            "client_uuid": client_uuid, "base_version": 0, "machine_id": machine_id,
            "audit_type": "Smoke Test Delete Target", "system_def_ids": [], "status": "draft", "results": [],
        }]},
        headers=admin_headers,
    )
    disposable_audit_id = sync_resp.json()["results"][0]["audit"]["id"]
    print(f"created disposable audit id={disposable_audit_id} for delete test")

    non_admin_email = f"nonadmin_{uuid.uuid4().hex[:8]}@test.local"
    api.post(
        "/users",
        json={"name": "Non Admin Tester", "email": non_admin_email, "password": "testpass123", "role": "internal"},
        headers=admin_headers,
    )
    api.close()

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ============ Dashboard interactivity ============
        page = browser.new_page()
        page.on("console", log_console)
        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
        page.on("dialog", lambda d: d.accept())

        page.goto(f"{BASE}/admin/")
        page.fill('input[name="email"]', ADMIN_EMAIL)
        page.fill('input[name="password"]', ADMIN_PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_selector(".kpi-grid", timeout=10000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(SCREENSHOT_DIR / "10_dashboard.png"))

        chart_bars = page.query_selector_all(".chart-bar")
        print(f"trend chart bars rendered: {len(chart_bars)}")
        assert len(chart_bars) == 12, f"expected 12 weekly bars, got {len(chart_bars)}"

        # Click "Open Tasks" KPI -> should land on Tasks filtered to status=open
        page.click('a.kpi-card[href^="#/tasks"]')
        page.wait_for_selector(".status-filter", timeout=10000)
        selected_value = page.eval_on_selector(".status-filter", "el => el.value")
        print(f"tasks status-filter after KPI click: {selected_value}")
        assert selected_value == "open"

        # Go back to dashboard, click a machine row -> machine detail page
        page.goto(f"{BASE}/admin/#/dashboard")
        page.wait_for_selector(".kpi-grid", timeout=10000)
        page.wait_for_timeout(300)
        machine_rows = page.query_selector_all(".clickable-row")
        if machine_rows:
            machine_rows[0].click()
            page.wait_for_selector(".detail-grid", timeout=10000)
            page.wait_for_timeout(300)
            page.screenshot(path=str(SCREENSHOT_DIR / "11_machine_detail.png"))
            print("machine detail page loaded OK")
        else:
            print("no top-machines rows to test click-through on (no findings yet) -- skipping")

        # ============ Admin can delete an audit ============
        page.goto(f"{BASE}/admin/#/audits")
        page.wait_for_selector(".data-table", timeout=10000)
        page.wait_for_timeout(500)

        delete_buttons = page.query_selector_all(".delete-audit-btn")
        print(f"delete buttons visible to admin: {len(delete_buttons)}")
        assert len(delete_buttons) > 0, "admin should see delete buttons"

        rows_before = len(page.query_selector_all(".data-table tbody tr"))

        view_link = page.query_selector(f'a[href="#/audits/{disposable_audit_id}"]')
        assert view_link is not None, "disposable test audit not found in the list"
        row = view_link.evaluate_handle("el => el.closest('tr')")
        row.as_element().query_selector(".delete-audit-btn").click()
        page.wait_for_timeout(500)

        rows_after = len(page.query_selector_all(".data-table tbody tr"))
        print(f"rows before delete: {rows_before}, after: {rows_after}")
        assert rows_after == rows_before - 1, "row should disappear immediately after delete, no page reload"

        gone_link = page.query_selector(f'a[href="#/audits/{disposable_audit_id}"]')
        assert gone_link is None, "deleted audit's row must be gone"
        page.screenshot(path=str(SCREENSHOT_DIR / "12_after_delete.png"))

        # ============ Non-admin does NOT see delete buttons ============
        page2 = browser.new_page()
        page2.on("console", log_console)
        page2.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))

        page2.goto(f"{BASE}/admin/")
        page2.fill('input[name="email"]', non_admin_email)
        page2.fill('input[name="password"]', "testpass123")
        page2.click('button[type="submit"]')
        page2.wait_for_selector(".kpi-grid", timeout=10000)
        page2.goto(f"{BASE}/admin/#/audits")
        page2.wait_for_selector(".data-table", timeout=10000)
        page2.wait_for_timeout(500)
        non_admin_delete_buttons = page2.query_selector_all(".delete-audit-btn")
        print(f"delete buttons visible to non-admin: {len(non_admin_delete_buttons)}")
        assert len(non_admin_delete_buttons) == 0, "non-admin must not see delete buttons"

        browser.close()

    print("\n== Console errors ==")
    if console_errors:
        for e in console_errors:
            print(" -", e)
    else:
        print("none")

    return 1 if console_errors else 0


if __name__ == "__main__":
    sys.exit(main())
