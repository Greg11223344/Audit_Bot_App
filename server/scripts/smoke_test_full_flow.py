"""End-to-end browser verification of the AuditType -> System -> SubModule -> ChecklistItem
feature: machine -> audit type -> system -> sub-module-grouped checklist with real text,
mid-audit report generation, admin audit detail grouping, and historical data integrity."""
import sys
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
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ============ Field app ============
        page = browser.new_page()
        page.on("console", log_console)
        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))

        page.goto(f"{BASE}/app/")
        page.fill('input[name="email"]', ADMIN_EMAIL)
        page.fill('input[name="password"]', ADMIN_PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_selector('[data-action="new-audit"]', timeout=10000)

        page.click('[data-action="new-audit"]')
        page.wait_for_selector(".machine-card", timeout=10000)
        page.click(".machine-card")

        # -- Audit type selection (new step) --
        page.wait_for_selector(".audit-type-list .machine-card", timeout=10000)
        audit_type_cards = page.query_selector_all(".audit-type-list .machine-card")
        labels = [ascii_safe(c.inner_text()) for c in audit_type_cards]
        print("audit types offered:", labels)
        assert len(audit_type_cards) == 2, f"expected 2 audit types, got {len(audit_type_cards)}"
        # Pick "Machine Audit" (first one, per checklist_data_v2.json order)
        audit_type_cards[0].click()

        # -- System selection, scoped to the chosen audit type --
        page.wait_for_selector(".system-row", timeout=10000)
        rows = page.query_selector_all(".system-row")
        row_labels = [ascii_safe(r.inner_text()) for r in rows]
        print("systems offered under Machine Audit:", row_labels)
        assert any(l.startswith("PreFeeder") for l in row_labels)
        prefeeder_row = next(r for r in rows if r.inner_text().startswith("PreFeeder"))
        prefeeder_row.query_selector("input").check()
        page.click(".continue-btn")

        # -- Checklist: grouped by sub-module, real text, not bare numbers --
        page.wait_for_selector(".checklist-item", timeout=10000)
        page.wait_for_timeout(300)
        sub_headings = page.eval_on_selector_all(".module-heading", "els => els.map(e => e.textContent)")
        print(f"sub-module headings ({len(sub_headings)}):", [ascii_safe(h) for h in sub_headings[:5]], "...")
        assert len(sub_headings) == 14, f"expected 14 PreFeeder sub-modules, got {len(sub_headings)}"

        descriptions = page.eval_on_selector_all(".checklist-item-desc", "els => els.map(e => e.textContent.trim())")
        print(f"item count: {len(descriptions)}")
        assert len(descriptions) == 52, f"expected 52 PreFeeder items, got {len(descriptions)}"
        assert not any(d.split(". ", 1)[-1].strip().isdigit() for d in descriptions), "bare-number item found"
        page.screenshot(path=str(SCREENSHOT_DIR / "01_checklist_grouped.png"))

        # -- Fill a couple of items, then generate a report MID-AUDIT (not yet submitted) --
        items = page.query_selector_all(".checklist-item")
        items[0].query_selector(".result-Pass").click()
        items[1].query_selector(".result-Fail").click()
        items[1].query_selector(".critical-flag input").check()
        page.wait_for_timeout(300)

        page.click(".report-btn")
        page.wait_for_selector(".report-area button", timeout=15000)
        with page.expect_download(timeout=10000) as dl_info:
            page.click(".report-area button")
        mid_audit_pdf = SCREENSHOT_DIR / "mid_audit_report.pdf"
        dl_info.value.save_as(str(mid_audit_pdf))
        print(f"MID-AUDIT report downloaded: {mid_audit_pdf.stat().st_size} bytes")
        assert mid_audit_pdf.stat().st_size > 500

        # -- Now submit and confirm final report still works --
        page.click(".review-btn")
        page.wait_for_selector(".review-stats", timeout=10000)
        page.on("dialog", lambda d: d.accept())
        page.click(".submit-btn")
        page.wait_for_selector(".report-area button", timeout=15000)
        with page.expect_download(timeout=10000) as dl_info2:
            page.click(".report-area button")
        final_pdf = SCREENSHOT_DIR / "final_report.pdf"
        dl_info2.value.save_as(str(final_pdf))
        print(f"FINAL report downloaded: {final_pdf.stat().st_size} bytes")

        # ============ Admin app ============
        page2 = browser.new_page()
        page2.on("console", log_console)
        page2.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))

        page2.goto(f"{BASE}/admin/")
        page2.fill('input[name="email"]', ADMIN_EMAIL)
        page2.fill('input[name="password"]', ADMIN_PASSWORD)
        page2.click('button[type="submit"]')
        page2.wait_for_selector(".kpi-grid", timeout=10000)

        page2.click('a[href="#/machines"]')
        page2.wait_for_selector(".system-group", state="attached", timeout=10000)
        # The systems list lives inside a collapsed <details> section by default; open it directly.
        page2.eval_on_selector(".systems-body", "el => el.closest('details').open = true")
        page2.wait_for_timeout(200)
        page2.screenshot(path=str(SCREENSHOT_DIR / "02_admin_machines_by_type.png"))
        groups = page2.query_selector_all(".system-group")
        print(f"admin system groups (by audit type): {len(groups)}")
        assert len(groups) == 2

        # -- Audit detail: verify a HISTORICAL audit (id=7, real legacy data) still renders with
        # grouped headings and real descriptions after the schema migration --
        page2.goto(f"{BASE}/admin/#/audits/7")
        page2.wait_for_selector(".results-list", timeout=10000)
        page2.wait_for_timeout(300)
        page2.screenshot(path=str(SCREENSHOT_DIR / "03_admin_audit7_detail.png"))
        result_descs = page2.eval_on_selector_all(".result-row-desc", "els => els.map(e => e.textContent)")
        print(f"audit 7 result descriptions ({len(result_descs)}):", [ascii_safe(d) for d in result_descs[:3]])
        assert len(result_descs) == 13, f"expected 13 results for historical audit 7, got {len(result_descs)}"

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
