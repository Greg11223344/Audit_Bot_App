import streamlit as st
import pandas as pd
from pathlib import Path
import fitz  # PyMuPDF
from datetime import datetime
import json
import hashlib

from modules.checklist_loader import load_all_audit_checks
from modules.report_generator import (
    generate_word_report,
    calculate_overall_summary,
    calculate_module_summaries,
    get_completed_results,
)
from modules.audit_session_manager import (
    save_audit_session,
    list_saved_audit_sessions,
    load_audit_session,
    get_saved_audit_display_name,
)


# =========================
# Paths
# =========================

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = BASE_DIR / "uploaded_images"
REPORTS_DIR = BASE_DIR / "output_reports"
SAVED_AUDITS_DIR = BASE_DIR / "saved_audits"

FULL_AUDIT_EXCEL_PATH = DATA_DIR / "Machine Audit Draft1.xlsx"
POST_INSTALLATION_EXCEL_PATH = DATA_DIR / "Post Installation Audit.xlsx"

PDF_PATH = DATA_DIR / "ACS Audit.pdf"
CUSTOMERS_PATH = DATA_DIR / "customers.xlsx"

IMAGES_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)
SAVED_AUDITS_DIR.mkdir(exist_ok=True)


# =========================
# Page Configuration
# =========================

st.set_page_config(
    page_title="Machine Audit Bot",
    page_icon="🛠️",
    layout="wide"
)


# =========================
# Audit Types
# =========================

AUDIT_TYPE_OPTIONS = [
    "Full Audit",
    "Post Installation Audit",
]


def get_audit_excel_path(audit_type: str) -> Path:
    if audit_type == "Post Installation Audit":
        return POST_INSTALLATION_EXCEL_PATH

    return FULL_AUDIT_EXCEL_PATH


# =========================
# Result Options
# =========================

RESULT_LABEL_OPTIONS = [
    "⚪ Not Checked",
    "✅ Pass",
    "⚠️ Near Fail",
    "❌ Fail",
    "➖ N/A",
]

RESULT_VALUE_MAP = {
    "⚪ Not Checked": "",
    "✅ Pass": "Pass",
    "⚠️ Near Fail": "Near Fail",
    "❌ Fail": "Fail",
    "➖ N/A": "N/A",
}

RESULT_REVERSE_MAP = {
    "": "⚪ Not Checked",
    "Pass": "✅ Pass",
    "Near Fail": "⚠️ Near Fail",
    "Fail": "❌ Fail",
    "N/A": "➖ N/A",
}


# =========================
# Helper Functions
# =========================

def check_file_exists(file_path: Path) -> bool:
    return file_path.exists() and file_path.is_file()


def load_excel_sheets(excel_path: Path):
    try:
        excel_file = pd.ExcelFile(excel_path)
        return excel_file.sheet_names, None
    except Exception as e:
        return [], str(e)


def load_pdf_info(pdf_path: Path):
    try:
        doc = fitz.open(pdf_path)
        page_count = len(doc)
        doc.close()
        return page_count, None
    except Exception as e:
        return 0, str(e)


def find_column(df, possible_names):
    normalized_columns = {
        str(col).strip().lower(): col
        for col in df.columns
    }

    for name in possible_names:
        key = str(name).strip().lower()
        if key in normalized_columns:
            return normalized_columns[key]

    return None


def load_customers(customers_path: Path):
    try:
        df = pd.read_excel(customers_path)
        df.columns = [str(col).strip() for col in df.columns]

        region_col = find_column(df, ["Region", "אזור"])

        site_col = find_column(df, [
            "Site",
            "Customer Name",
            "Customer",
            "Client",
            "Client Name",
            "לקוח",
            "שם לקוח",
            "שם הלקוח",
            "אתר",
            "מיקום",
        ])

        serial_col = find_column(df, [
            "SN",
            "S/N",
            "Machine Serial Number",
            "Machine SN",
            "Serial Number",
            "Machine Serial",
            "מספר סידורי",
            "מספר מכונה",
            "סיריאל",
        ])

        machine_type_col = find_column(df, [
            "Machine Type",
            "Machine",
            "Type",
            "Model",
            "Machine Model",
            "סוג מכונה",
            "דגם",
        ])

        engineer_owner_col = find_column(df, [
            "Engineer Owner",
            "Engineer",
            "Owner",
            "HP Engineer",
            "מהנדס",
            "מהנדס אחראי",
        ])

        missing_required = []

        if site_col is None:
            missing_required.append("Site / Customer Name / Customer / לקוח")

        if serial_col is None:
            missing_required.append("SN / Machine Serial Number / מספר סידורי")

        if missing_required:
            return pd.DataFrame(), (
                "Missing required customer columns: "
                + str(missing_required)
                + ". Existing columns are: "
                + str(list(df.columns))
            )

        customers_df = pd.DataFrame()

        customers_df["Customer Name"] = df[site_col].fillna("").astype(str).str.strip()
        customers_df["Site"] = df[site_col].fillna("").astype(str).str.strip()
        customers_df["Machine Serial Number"] = df[serial_col].fillna("").astype(str).str.strip()

        if region_col:
            customers_df["Region"] = df[region_col].fillna("").astype(str).str.strip()
        else:
            customers_df["Region"] = ""

        if machine_type_col:
            customers_df["Machine Type"] = df[machine_type_col].fillna("").astype(str).str.strip()
        else:
            customers_df["Machine Type"] = "HP Scitex C5X0"

        if engineer_owner_col:
            customers_df["Engineer Owner"] = df[engineer_owner_col].fillna("").astype(str).str.strip()
        else:
            customers_df["Engineer Owner"] = ""

        customers_df = customers_df[
            (customers_df["Customer Name"] != "") &
            (customers_df["Machine Serial Number"] != "")
        ]

        return customers_df, None

    except Exception as e:
        return pd.DataFrame(), str(e)


def safe_path_text(value):
    value = str(value)
    invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']

    for char in invalid_chars:
        value = value.replace(char, "_")

    value = value.replace(" ", "_")
    return value


def save_uploaded_image(uploaded_file, customer, machine_sn, module_name, check_key):
    if uploaded_file is None:
        return ""

    safe_customer = safe_path_text(customer)
    safe_machine = safe_path_text(machine_sn)
    safe_module = safe_path_text(module_name)
    safe_check_key = safe_path_text(check_key)

    folder = IMAGES_DIR / safe_customer / safe_machine / safe_module
    folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_extension = Path(uploaded_file.name).suffix

    image_name = f"{safe_check_key}_{timestamp}{file_extension}"
    image_path = folder / image_name

    with open(image_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return str(image_path)


def is_image_required(check_description: str) -> bool:
    text = str(check_description).lower()

    image_keywords = [
        "picture",
        "photo",
        "image",
        "add picture",
        "add photo",
        "take picture",
        "take photo",
        "send pic",
        "scanner picture",
        "scanners",
    ]

    return any(keyword in text for keyword in image_keywords)


def has_valid_image(item: dict) -> bool:
    image_path = str(item.get("image_path", "")).strip()

    if not image_path:
        return False

    return Path(image_path).exists()


def find_missing_required_images(audit_results: dict):
    completed_results = get_completed_results(audit_results)
    missing_items = []

    for key, item in completed_results.items():
        if is_image_required(item.get("check_description", "")) and not has_valid_image(item):
            missing_items.append({
                "key": key,
                "module": item.get("module", ""),
                "sub_module": item.get("sub_module", ""),
                "check_number": item.get("check_number", ""),
                "check_description": item.get("check_description", ""),
                "result": item.get("result", ""),
            })

    return missing_items


def calculate_module_summary_from_items(module_items: dict):
    completed_items = get_completed_results(module_items)

    total = len(completed_items)
    pass_count = 0
    near_fail_count = 0
    fail_count = 0
    na_count = 0

    for item in completed_items.values():
        result = item.get("result", "")

        if result == "Pass":
            pass_count += 1
        elif result == "Near Fail":
            near_fail_count += 1
        elif result == "Fail":
            fail_count += 1
        elif result == "N/A":
            na_count += 1

    counted_checks = total - na_count

    if counted_checks > 0:
        score = round(((pass_count + near_fail_count * 0.5) / counted_checks) * 100, 1)
    else:
        score = 0

    return {
        "total": total,
        "pass": pass_count,
        "near_fail": near_fail_count,
        "fail": fail_count,
        "na": na_count,
        "score": score,
    }


def get_machine_level(score, fail_count):
    if fail_count >= 10:
        return "D - Not Approved"

    if score >= 90:
        return "A - Excellent"
    elif score >= 75:
        return "B - Good"
    elif score >= 60:
        return "C - Needs Improvement"
    else:
        return "D - Not Approved"


def initialize_all_audit_results(excel_path: Path):
    all_checks_df, load_errors = load_all_audit_checks(excel_path)

    if load_errors:
        st.warning("Some modules could not be loaded:")
        for error in load_errors:
            st.write(f"- {error}")

    if all_checks_df.empty:
        return False, "No audit checks were loaded from the Excel file."

    st.session_state.all_checks_df = all_checks_df
    st.session_state.audit_results = {}

    for _, row in all_checks_df.iterrows():
        check_key = row["Check Key"]

        st.session_state.audit_results[check_key] = {
            "module": row["Module"],
            "sub_module": row["Sub Module"],
            "check_number": row["Check Number"],
            "check_description": row["Check Description"],
            "result": "",
            "comment": "",
            "image_path": "",
        }

    return True, f"Loaded {len(all_checks_df)} checks from: {excel_path.name}"


def rebuild_checks_dataframe_from_results(audit_results: dict):
    rows = []

    for check_key, item in audit_results.items():
        rows.append({
            "Module": item.get("module", ""),
            "Sub Module": item.get("sub_module", ""),
            "Check Number": item.get("check_number", ""),
            "Check Description": item.get("check_description", ""),
            "Check Key": check_key,
            "Result": item.get("result", ""),
            "Comment": item.get("comment", ""),
            "Image Path": item.get("image_path", ""),
        })

    return pd.DataFrame(rows)


def validate_required_fields(fields: dict):
    missing = []

    for field_name, field_value in fields.items():
        if str(field_value).strip() == "":
            missing.append(field_name)

    return missing


def clear_current_session():
    st.session_state.audit_started = False
    st.session_state.audit_details = {}
    st.session_state.audit_results = {}
    st.session_state.all_checks_df = pd.DataFrame()
    st.session_state.loaded_session_file = ""
    st.session_state.last_auto_save_hash = ""
    st.session_state.last_auto_save_time = ""


# =========================
# Auto Save
# =========================

def build_auto_save_hash() -> str:
    payload = {
        "audit_details": st.session_state.get("audit_details", {}),
        "audit_results": st.session_state.get("audit_results", {}),
    }

    payload_text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )

    return hashlib.md5(payload_text.encode("utf-8")).hexdigest()


def auto_save_current_audit():
    if not st.session_state.get("audit_started", False):
        return

    if not st.session_state.get("audit_details"):
        return

    if not st.session_state.get("audit_results"):
        return

    current_hash = build_auto_save_hash()

    if current_hash == st.session_state.get("last_auto_save_hash", ""):
        return

    existing_file_path = None

    if st.session_state.get("loaded_session_file"):
        existing_file_path = Path(st.session_state.loaded_session_file)

    saved_file_path = save_audit_session(
        audit_details=st.session_state.audit_details,
        audit_results=st.session_state.audit_results,
        saved_audits_dir=SAVED_AUDITS_DIR,
        existing_file_path=existing_file_path,
    )

    st.session_state.loaded_session_file = str(saved_file_path)
    st.session_state.last_auto_save_hash = current_hash
    st.session_state.last_auto_save_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =========================
# Session State
# =========================

if "audit_started" not in st.session_state:
    st.session_state.audit_started = False

if "audit_details" not in st.session_state:
    st.session_state.audit_details = {}

if "audit_results" not in st.session_state:
    st.session_state.audit_results = {}

if "all_checks_df" not in st.session_state:
    st.session_state.all_checks_df = pd.DataFrame()

if "loaded_session_file" not in st.session_state:
    st.session_state.loaded_session_file = ""

if "last_auto_save_hash" not in st.session_state:
    st.session_state.last_auto_save_hash = ""

if "last_auto_save_time" not in st.session_state:
    st.session_state.last_auto_save_time = ""


# =========================
# UI
# =========================

st.title("🛠️ Machine Audit Bot")
st.subheader("ACS / Machine Audit Interface")

st.markdown("---")


# =========================
# 1. System Files Check
# =========================

st.header("1. System Files Check")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.write("### Excel Checklists")

    if check_file_exists(FULL_AUDIT_EXCEL_PATH):
        st.success(f"Full Audit found: {FULL_AUDIT_EXCEL_PATH.name}")

        sheet_names, excel_error = load_excel_sheets(FULL_AUDIT_EXCEL_PATH)

        if excel_error:
            st.error(f"Full Audit loading error: {excel_error}")
        else:
            st.write(f"Full Audit sheets: {len(sheet_names)}")
    else:
        st.error("Full Audit Excel file not found.")
        st.info("Place 'Machine Audit Draft1.xlsx' inside the data folder.")

    if check_file_exists(POST_INSTALLATION_EXCEL_PATH):
        st.success(f"Post Installation found: {POST_INSTALLATION_EXCEL_PATH.name}")

        sheet_names, excel_error = load_excel_sheets(POST_INSTALLATION_EXCEL_PATH)

        if excel_error:
            st.error(f"Post Installation loading error: {excel_error}")
        else:
            st.write(f"Post Installation sheets: {len(sheet_names)}")
    else:
        st.error("Post Installation Excel file not found.")
        st.info("Place 'Post Installation Audit.xlsx' inside the data folder.")


with col2:
    st.write("### PDF Procedure")

    if check_file_exists(PDF_PATH):
        st.success(f"PDF file found: {PDF_PATH.name}")

        page_count, pdf_error = load_pdf_info(PDF_PATH)

        if pdf_error:
            st.error(f"PDF loading error: {pdf_error}")
        else:
            st.write(f"PDF pages: {page_count}")
    else:
        st.error("PDF file not found.")
        st.info("Place 'ACS Audit.pdf' inside the data folder.")


with col3:
    st.write("### Customers Database")

    if check_file_exists(CUSTOMERS_PATH):
        st.success(f"Customers file found: {CUSTOMERS_PATH.name}")

        customers_df, customers_error = load_customers(CUSTOMERS_PATH)

        if customers_error:
            st.error(customers_error)
        else:
            st.write(f"Customers rows: {len(customers_df)}")
            st.write(f"Unique customers: {customers_df['Customer Name'].nunique()}")
    else:
        customers_df = pd.DataFrame()
        st.error("customers.xlsx file not found.")
        st.info("Place 'customers.xlsx' inside the data folder.")


with col4:
    st.write("### Saved Audits")

    saved_files_count = len(list_saved_audit_sessions(SAVED_AUDITS_DIR))
    st.success(f"Saved audits: {saved_files_count}")


st.markdown("---")


# =========================
# 2. Session Management
# =========================

st.header("2. Session Management")

session_col1, session_col2 = st.columns(2)

with session_col1:
    st.write("### Load Existing Audit")

    saved_audit_files = list_saved_audit_sessions(SAVED_AUDITS_DIR)

    if saved_audit_files:
        saved_display_options = [
            get_saved_audit_display_name(file_path)
            for file_path in saved_audit_files
        ]

        selected_saved_display = st.selectbox(
            "Select Saved Audit",
            options=saved_display_options,
            index=0
        )

        selected_saved_index = saved_display_options.index(selected_saved_display)
        selected_saved_file = saved_audit_files[selected_saved_index]

        if st.button("Load Existing Audit"):
            audit_details, audit_results, saved_at = load_audit_session(selected_saved_file)

            if "Audit Type" not in audit_details:
                audit_details["Audit Type"] = "Full Audit"

            if "Checklist File" not in audit_details:
                audit_details["Checklist File"] = "Unknown"

            st.session_state.audit_started = True
            st.session_state.audit_details = audit_details
            st.session_state.audit_results = audit_results
            st.session_state.all_checks_df = rebuild_checks_dataframe_from_results(audit_results)
            st.session_state.loaded_session_file = str(selected_saved_file)
            st.session_state.last_auto_save_hash = build_auto_save_hash()
            st.session_state.last_auto_save_time = saved_at

            st.success("Existing audit loaded successfully.")
            st.write(f"Loaded saved audit from: {saved_at}")
            st.rerun()
    else:
        st.info("No saved audits found yet.")


with session_col2:
    st.write("### Current Session")

    if st.session_state.audit_started:
        st.success("There is an active audit session.")

        current_audit_type = st.session_state.audit_details.get("Audit Type", "Full Audit")
        st.write(f"Audit Type: {current_audit_type}")

        if st.session_state.last_auto_save_time:
            st.write(f"Last Auto Save: {st.session_state.last_auto_save_time}")

        if st.session_state.loaded_session_file:
            st.write(f"Saved file: {st.session_state.loaded_session_file}")
        else:
            st.write("Current session is not saved yet.")

        if st.button("Clear Current Session"):
            clear_current_session()
            st.success("Current session cleared.")
            st.rerun()
    else:
        st.info("No active audit session.")


st.markdown("---")


# =========================
# 3. Machine Details
# =========================

st.header("3. Machine Details")

if not CUSTOMERS_PATH.exists():
    st.error("Cannot load customer dropdown because customers.xlsx was not found.")
    st.stop()

customers_df, customers_error = load_customers(CUSTOMERS_PATH)

if customers_error:
    st.error("Cannot load customer dropdown until customers.xlsx is fixed.")
    st.error(customers_error)
    st.stop()

if customers_df.empty:
    st.error("customers.xlsx is empty or does not contain valid customer rows.")
    st.stop()


selected_audit_type = st.selectbox(
    "Audit Type *",
    options=AUDIT_TYPE_OPTIONS,
    index=0
)

selected_excel_path = get_audit_excel_path(selected_audit_type)

if not check_file_exists(selected_excel_path):
    st.error(f"The selected audit Excel file was not found: {selected_excel_path.name}")
    st.stop()

customer_list = sorted(customers_df["Customer Name"].dropna().unique().tolist())

selected_customer = st.selectbox(
    "Customer / Site *",
    options=customer_list,
    index=0
)

customer_machines_df = customers_df[
    customers_df["Customer Name"] == selected_customer
].copy()

machine_list = customer_machines_df["Machine Serial Number"].dropna().unique().tolist()

selected_machine_sn = st.selectbox(
    "Machine Serial Number *",
    options=machine_list,
    index=0
)

selected_row = customer_machines_df[
    customer_machines_df["Machine Serial Number"] == selected_machine_sn
].iloc[0]


col_a, col_b = st.columns(2)

with col_a:
    machine_type = st.text_input(
        "Machine Type *",
        value=selected_row["Machine Type"]
    )

    site = st.text_input(
        "Site *",
        value=selected_row["Site"]
    )

with col_b:
    region = st.text_input(
        "Region *",
        value=selected_row["Region"]
    )

    audit_date = st.date_input("Audit Date *")


st.markdown("---")


# =========================
# 4. Reporting To
# =========================

st.header("4. Reporting To")

col_r1, col_r2 = st.columns(2)

with col_r1:
    engineer_owner = st.text_input(
        "Engineer Owner *",
        value=selected_row["Engineer Owner"]
    )

with col_r2:
    audit_engineer = st.text_input(
        "Audit Engineer Name *",
        value=selected_row["Engineer Owner"]
    )


st.markdown("---")


# =========================
# 5. Start New Audit
# =========================

st.header("5. Start New Audit")

if st.session_state.audit_started:
    st.error(
        "There is already an active audit session. "
        "Starting a new audit will replace it in memory. "
        "The current audit is protected by Auto Save, but you must confirm before starting a new one."
    )

    confirm_start_new = st.checkbox(
        "I understand that this will start a new audit and replace the current active session."
    )
else:
    st.info("No active audit session. You can start a new audit.")
    confirm_start_new = True

st.write(f"Selected Audit Type: **{selected_audit_type}**")
st.write(f"Selected Checklist File: **{selected_excel_path.name}**")

start_new_disabled = st.session_state.audit_started and not confirm_start_new

if st.button("Start New Audit", disabled=start_new_disabled):
    required_fields = {
        "Audit Type": selected_audit_type,
        "Customer / Site": selected_customer,
        "Machine Serial Number": selected_machine_sn,
        "Machine Type": machine_type,
        "Site": site,
        "Region": region,
        "Engineer Owner": engineer_owner,
        "Audit Engineer Name": audit_engineer,
        "Audit Date": audit_date,
    }

    missing_fields = validate_required_fields(required_fields)

    if missing_fields:
        st.error("Please fill all required fields before starting the audit:")
        for field in missing_fields:
            st.write(f"- {field}")
    else:
        success, message = initialize_all_audit_results(selected_excel_path)

        if not success:
            st.error(message)
        else:
            st.session_state.audit_started = True
            st.session_state.loaded_session_file = ""
            st.session_state.last_auto_save_hash = ""
            st.session_state.last_auto_save_time = ""

            st.session_state.audit_details = {
                "Audit Type": selected_audit_type,
                "Checklist File": selected_excel_path.name,
                "Customer / Site": selected_customer,
                "Machine SN": selected_machine_sn,
                "Machine Type": machine_type,
                "Site": site,
                "Region": region,
                "Audit Date": str(audit_date),
                "Engineer Owner": engineer_owner,
                "Audit Engineer": audit_engineer,
            }

            auto_save_current_audit()

            st.success("New audit session started successfully.")
            st.success(message)
            st.rerun()


if st.session_state.audit_started:
    st.write("### Current Audit Details")

    for key, value in st.session_state.audit_details.items():
        st.write(f"{key}: {value}")


st.markdown("---")


# =========================
# 6. Audit Checklist
# =========================

if st.session_state.audit_started:

    st.header("6. Audit Checklist")

    current_audit_type = st.session_state.audit_details.get("Audit Type", "Full Audit")
    st.write(f"### Active Audit Type: {current_audit_type}")

    if st.session_state.last_auto_save_time:
        st.caption(f"Auto Save active. Last saved: {st.session_state.last_auto_save_time}")

    if st.session_state.all_checks_df.empty:
        st.error("No checklist data is loaded.")
    else:
        modules = sorted(st.session_state.all_checks_df["Module"].dropna().unique().tolist())

        selected_module = st.selectbox(
            "Select Machine Module",
            options=modules,
            index=0
        )

        module_check_keys = []

        for check_key, item in st.session_state.audit_results.items():
            if item.get("module") == selected_module:
                module_check_keys.append(check_key)

        module_results = {
            key: st.session_state.audit_results[key]
            for key in module_check_keys
        }

        completed_module_results = get_completed_results(module_results)

        st.success(f"Loaded {len(module_check_keys)} checks from module: {selected_module}")
        st.info(f"Performed checks in this module: {len(completed_module_results)}")

        st.write("### Engineer Checklist")

        for check_key in module_check_keys:
            item = st.session_state.audit_results[check_key]

            current_result = item.get("result", "")
            current_comment = item.get("comment", "")
            current_image_path = item.get("image_path", "")
            image_required = is_image_required(item.get("check_description", ""))
            valid_image_exists = has_valid_image(item)

            status_icon = "⚪"

            if current_result == "Pass":
                status_icon = "✅"
            elif current_result == "Near Fail":
                status_icon = "⚠️"
            elif current_result == "Fail":
                status_icon = "❌"
            elif current_result == "N/A":
                status_icon = "➖"
            elif current_comment or current_image_path:
                status_icon = "📝"

            if image_required and not valid_image_exists and (current_result or current_comment):
                status_icon = "📷⚠️"

            image_required_text = " | 📷 Image Required" if image_required else ""

            with st.expander(
                f"{status_icon} {item['sub_module']} | Check {item['check_number']}: {item['check_description']}{image_required_text}",
                expanded=False
            ):
                st.write(f"**Module:** {item['module']}")
                st.write(f"**Sub Module:** {item['sub_module']}")
                st.write(f"**Check Number:** {item['check_number']}")
                st.write(f"**Check Description:** {item['check_description']}")

                if image_required:
                    st.warning("📷 Image is required for this check.")

                current_result_label = RESULT_REVERSE_MAP.get(current_result, "⚪ Not Checked")

                selected_result_label = st.selectbox(
                    "Result",
                    options=RESULT_LABEL_OPTIONS,
                    index=RESULT_LABEL_OPTIONS.index(current_result_label),
                    key=f"result_{check_key}",
                )

                result = RESULT_VALUE_MAP[selected_result_label]

                comment = st.text_area(
                    "Engineer Comment",
                    value=current_comment,
                    key=f"comment_{check_key}"
                )

                uploaded_image = st.file_uploader(
                    "Upload Image",
                    type=["png", "jpg", "jpeg"],
                    key=f"image_{check_key}"
                )

                image_path = current_image_path

                if uploaded_image is not None:
                    image_path = save_uploaded_image(
                        uploaded_image,
                        st.session_state.audit_details["Customer / Site"],
                        st.session_state.audit_details["Machine SN"],
                        selected_module,
                        check_key
                    )

                    st.image(image_path, width=300)
                    st.success("Image uploaded and saved.")

                elif image_path:
                    st.image(image_path, width=300)

                st.session_state.audit_results[check_key] = {
                    "module": item["module"],
                    "sub_module": item["sub_module"],
                    "check_number": item["check_number"],
                    "check_description": item["check_description"],
                    "result": result,
                    "comment": comment,
                    "image_path": image_path,
                }

                updated_item = st.session_state.audit_results[check_key]

                if (
                    image_required
                    and get_completed_results({check_key: updated_item})
                    and not has_valid_image(updated_item)
                ):
                    st.error("This check requires an image. Please upload an image before generating the report.")

        auto_save_current_audit()

        st.markdown("---")

        st.header("7. Module Summary")

        updated_module_results = {
            key: st.session_state.audit_results[key]
            for key in module_check_keys
        }

        completed_updated_module_results = get_completed_results(updated_module_results)

        summary = calculate_module_summary_from_items(completed_updated_module_results)
        module_level = get_machine_level(summary["score"], summary["fail"])

        missing_module_images = find_missing_required_images(updated_module_results)

        col_s1, col_s2, col_s3, col_s4, col_s5, col_s6, col_s7 = st.columns(7)

        col_s1.metric("Total Checks", len(module_check_keys))
        col_s2.metric("Performed", summary["total"])
        col_s3.metric("Pass", summary["pass"])
        col_s4.metric("Near Fail", summary["near_fail"])
        col_s5.metric("Fail", summary["fail"])
        col_s6.metric("N/A", summary["na"])
        col_s7.metric("Score", f"{summary['score']}%")

        st.write(f"### Module Level: {module_level}")

        if missing_module_images:
            st.error("Some performed checks in this module require images but no image was uploaded.")

            missing_module_rows = []
            for missing in missing_module_images:
                missing_module_rows.append({
                    "Sub Module": missing["sub_module"],
                    "Check No.": missing["check_number"],
                    "Check Description": missing["check_description"],
                    "Result": missing["result"],
                })

            st.dataframe(
                pd.DataFrame(missing_module_rows),
                use_container_width=True,
                hide_index=True
            )


# =========================
# 8. Overall Report + Save Progress
# =========================

if st.session_state.audit_started and st.session_state.audit_results:

    st.markdown("---")
    st.header("8. Overall Report")

    auto_save_current_audit()

    completed_results = get_completed_results(st.session_state.audit_results)
    missing_required_images = find_missing_required_images(st.session_state.audit_results)

    overall_summary = calculate_overall_summary(st.session_state.audit_results)
    overall_level = get_machine_level(overall_summary["score"], overall_summary["fail"])

    col_o1, col_o2, col_o3, col_o4, col_o5, col_o6, col_o7 = st.columns(7)

    col_o1.metric("Total Checks", len(st.session_state.audit_results))
    col_o2.metric("Performed", overall_summary["performed"])
    col_o3.metric("Pass", overall_summary["pass"])
    col_o4.metric("Near Fail", overall_summary["near_fail"])
    col_o5.metric("Fail", overall_summary["fail"])
    col_o6.metric("N/A", overall_summary["na"])
    col_o7.metric("Score", f"{overall_summary['score']}%")

    st.write(f"### Overall Machine Level: {overall_level}")

    if st.session_state.last_auto_save_time:
        st.success(f"Auto Saved: {st.session_state.last_auto_save_time}")

    st.write("### Summary by Module")

    module_summaries = calculate_module_summaries(st.session_state.audit_results)

    module_summary_rows = []

    for module, data in module_summaries.items():
        module_summary_rows.append({
            "Module": module,
            "Total Checks": data["total_checks"],
            "Performed": data["performed"],
            "Performed %": f"{data['performed_percent']}%",
            "Pass": data["pass"],
            "Near Fail": data["near_fail"],
            "Fail": data["fail"],
            "N/A": data["na"],
            "Score": f"{data['score']}%",
        })

    if module_summary_rows:
        st.dataframe(
            pd.DataFrame(module_summary_rows),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No performed checks yet.")

    if missing_required_images:
        st.error("Report cannot be generated because some performed checks require images.")

        missing_rows = []
        for missing in missing_required_images:
            missing_rows.append({
                "Module": missing["module"],
                "Sub Module": missing["sub_module"],
                "Check No.": missing["check_number"],
                "Check Description": missing["check_description"],
                "Result": missing["result"],
            })

        st.dataframe(
            pd.DataFrame(missing_rows),
            use_container_width=True,
            hide_index=True
        )

    st.info(
        "The report will include only checks that were actually performed or filled "
        "(Result / Comment / Image). Checks containing picture/photo/image/send pic require an uploaded image. "
        "Near Fail is calculated as 50% of a Pass."
    )

    st.markdown("---")
    st.subheader("Manual Save Audit Progress")

    if st.button("Save Audit Progress Now"):
        existing_file_path = None

        if st.session_state.loaded_session_file:
            existing_file_path = Path(st.session_state.loaded_session_file)

        saved_file_path = save_audit_session(
            audit_details=st.session_state.audit_details,
            audit_results=st.session_state.audit_results,
            saved_audits_dir=SAVED_AUDITS_DIR,
            existing_file_path=existing_file_path,
        )

        st.session_state.loaded_session_file = str(saved_file_path)
        st.session_state.last_auto_save_hash = build_auto_save_hash()
        st.session_state.last_auto_save_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        st.success("Audit progress saved successfully.")
        st.write(f"Saved file: {saved_file_path}")

    st.markdown("---")

    if st.button("Generate Word Report"):
        auto_save_current_audit()

        if not completed_results:
            st.warning("No performed checks found. Fill at least one check before generating a report.")
        elif missing_required_images:
            st.error("Cannot generate report. Upload the required images first.")
        else:
            report_path, report_summary, report_level = generate_word_report(
                audit_details=st.session_state.audit_details,
                audit_results=st.session_state.audit_results,
                output_dir=REPORTS_DIR,
            )

            st.success("Word report generated successfully.")
            st.write(f"Machine Level: {report_level}")
            st.write(f"Report path: {report_path}")

            with open(report_path, "rb") as file:
                st.download_button(
                    label="Download Word Report",
                    data=file,
                    file_name=Path(report_path).name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )

else:
    if not st.session_state.audit_started:
        st.info("Start a new audit or load an existing saved audit.")