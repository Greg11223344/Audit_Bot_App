import json
import re
from pathlib import Path
from datetime import datetime


# =========================
# Helpers
# =========================

def safe_text(value) -> str:
    if value is None:
        return ""

    return str(value).strip()


def safe_filename_text(value) -> str:
    value = safe_text(value)

    invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']

    for char in invalid_chars:
        value = value.replace(char, "_")

    value = value.replace(" ", "_")
    value = re.sub(r"_+", "_", value)

    return value.strip("_")


def build_session_filename(audit_details: dict) -> str:
    customer = safe_filename_text(audit_details.get("Customer / Site", "Customer"))
    machine_sn = safe_filename_text(audit_details.get("Machine SN", "Machine"))
    audit_type = safe_filename_text(audit_details.get("Audit Type", "Full Audit"))
    audit_date = safe_filename_text(audit_details.get("Audit Date", datetime.now().strftime("%Y-%m-%d")))

    if not customer:
        customer = "Customer"

    if not machine_sn:
        machine_sn = "Machine"

    if not audit_type:
        audit_type = "Full_Audit"

    if not audit_date:
        audit_date = datetime.now().strftime("%Y-%m-%d")

    return f"{customer}_{machine_sn}_{audit_type}_{audit_date}.json"


# =========================
# Save / Load
# =========================

def save_audit_session(
    audit_details: dict,
    audit_results: dict,
    saved_audits_dir,
    existing_file_path=None,
):
    saved_audits_dir = Path(saved_audits_dir)
    saved_audits_dir.mkdir(parents=True, exist_ok=True)

    saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "version": "2.0",
        "saved_at": saved_at,
        "audit_details": audit_details,
        "audit_results": audit_results,
    }

    if existing_file_path:
        file_path = Path(existing_file_path)
    else:
        file_name = build_session_filename(audit_details)
        file_path = saved_audits_dir / file_name

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return file_path


def load_audit_session(file_path):
    file_path = Path(file_path)

    with open(file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    audit_details = payload.get("audit_details", {})
    audit_results = payload.get("audit_results", {})
    saved_at = payload.get("saved_at", "")

    if "Audit Type" not in audit_details:
        audit_details["Audit Type"] = "Full Audit"

    if "Checklist File" not in audit_details:
        audit_details["Checklist File"] = "Unknown"

    return audit_details, audit_results, saved_at


def list_saved_audit_sessions(saved_audits_dir):
    saved_audits_dir = Path(saved_audits_dir)
    saved_audits_dir.mkdir(parents=True, exist_ok=True)

    files = list(saved_audits_dir.glob("*.json"))

    files = sorted(
        files,
        key=lambda file_path: file_path.stat().st_mtime,
        reverse=True
    )

    return files


def get_saved_audit_display_name(file_path):
    file_path = Path(file_path)

    try:
        audit_details, audit_results, saved_at = load_audit_session(file_path)

        audit_type = audit_details.get("Audit Type", "Full Audit")
        customer = audit_details.get("Customer / Site", "")
        machine_sn = audit_details.get("Machine SN", "")
        audit_date = audit_details.get("Audit Date", "")

        parts = []

        if audit_type:
            parts.append(audit_type)

        if customer:
            parts.append(customer)

        if machine_sn:
            parts.append(machine_sn)

        if audit_date:
            parts.append(str(audit_date))

        if saved_at:
            parts.append(f"Saved: {saved_at}")

        if parts:
            return " | ".join(parts)

        return file_path.name

    except Exception:
        return file_path.name