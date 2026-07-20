import hashlib
import re
from pathlib import Path

import pandas as pd


# =========================
# Text Helpers
# =========================

def clean_text(value) -> str:
    if pd.isna(value):
        return ""

    text = str(value).replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def is_empty(value) -> bool:
    return clean_text(value) == ""


def is_column_placeholder(value) -> bool:
    text = clean_text(value).lower()
    return bool(re.fullmatch(r"column\s*\d+", text))


def is_valid_check_text(value) -> bool:
    text = clean_text(value)

    if not text:
        return False

    if is_column_placeholder(text):
        return False

    if text.lower() in ["nan", "none", "null"]:
        return False

    return True


def make_check_key(module: str, sub_module: str, check_number: str, description: str) -> str:
    raw = f"{module}|{sub_module}|{check_number}|{description}"
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]

    safe_module = re.sub(r"[^A-Za-z0-9]+", "_", module).strip("_")
    safe_sub_module = re.sub(r"[^A-Za-z0-9]+", "_", sub_module).strip("_")

    if not safe_module:
        safe_module = "Module"

    if not safe_sub_module:
        safe_sub_module = "SubModule"

    return f"{safe_module}_{safe_sub_module}_{check_number}_{digest}"


def find_column(df: pd.DataFrame, possible_names):
    normalized_columns = {
        clean_text(col).lower(): col
        for col in df.columns
    }

    for name in possible_names:
        key = clean_text(name).lower()
        if key in normalized_columns:
            return normalized_columns[key]

    return None


# =========================
# Standard Checklist Parser
# =========================

def parse_standard_sheet(excel_path: Path, sheet_name: str):
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    df.columns = [clean_text(col) for col in df.columns]

    module_col = find_column(df, [
        "Module",
        "Machine Module",
        "Area",
        "System",
    ])

    sub_module_col = find_column(df, [
        "Sub Module",
        "SubModule",
        "Sub-Module",
        "Sub module",
        "Section",
        "Topic",
    ])

    check_number_col = find_column(df, [
        "Check Number",
        "Check No.",
        "Check No",
        "No.",
        "No",
        "Number",
        "#",
    ])

    check_description_col = find_column(df, [
        "Check Description",
        "Description",
        "Check",
        "Inspection",
        "Audit Check",
        "Requirement",
        "Procedure",
    ])

    if check_description_col is None:
        return []

    rows = []
    running_number = 1

    for _, row in df.iterrows():
        description = clean_text(row.get(check_description_col, ""))

        if not is_valid_check_text(description):
            continue

        module = clean_text(row.get(module_col, "")) if module_col else clean_text(sheet_name)
        sub_module = clean_text(row.get(sub_module_col, "")) if sub_module_col else clean_text(sheet_name)

        if not module:
            module = clean_text(sheet_name)

        if not sub_module:
            sub_module = module

        if check_number_col:
            check_number = clean_text(row.get(check_number_col, ""))
        else:
            check_number = str(running_number)

        if not check_number:
            check_number = str(running_number)

        check_key = make_check_key(module, sub_module, check_number, description)

        rows.append({
            "Module": module,
            "Sub Module": sub_module,
            "Check Number": check_number,
            "Check Description": description,
            "Check Key": check_key,
        })

        running_number += 1

    return rows


# =========================
# Matrix Checklist Parser
# Used for Post Installation Audit.xlsx
# =========================

def parse_matrix_sheet(excel_path: Path, sheet_name: str):
    # header=0 (not None): these sheets have a real header row ("Sub Module", "1", "2", ...).
    # Reading with header=None used to treat that header row as a data row, producing a bogus
    # first "item" per module whose description was just the column number ("1", "2", ...).
    df = pd.read_excel(excel_path, sheet_name=sheet_name, header=0)
    df = df.dropna(how="all")
    df = df.dropna(axis=1, how="all")

    rows = []
    module = clean_text(sheet_name)
    current_sub_module = module
    check_counter = 1

    if df.empty:
        return rows

    for _, row in df.iterrows():
        values = [clean_text(value) for value in row.tolist()]
        values = [value for value in values if value != ""]

        if not values:
            continue

        non_placeholder_values = [
            value for value in values
            if not is_column_placeholder(value)
        ]

        if not non_placeholder_values:
            continue

        raw_first_cell = clean_text(row.iloc[0]) if len(row) > 0 else ""

        has_first_cell = bool(raw_first_cell) and not is_column_placeholder(raw_first_cell)

        other_cells = []
        for value in row.iloc[1:].tolist():
            text = clean_text(value)
            if is_valid_check_text(text):
                other_cells.append(text)

        if has_first_cell and other_cells:
            current_sub_module = raw_first_cell
            checks_in_row = other_cells
        elif has_first_cell and not other_cells:
            current_sub_module = raw_first_cell
            checks_in_row = []
        else:
            checks_in_row = [
                clean_text(value)
                for value in row.tolist()
                if is_valid_check_text(value)
            ]

        for description in checks_in_row:
            if not is_valid_check_text(description):
                continue

            check_number = str(check_counter)
            check_key = make_check_key(module, current_sub_module, check_number, description)

            rows.append({
                "Module": module,
                "Sub Module": current_sub_module,
                "Check Number": check_number,
                "Check Description": description,
                "Check Key": check_key,
            })

            check_counter += 1

    return rows


# =========================
# Parser Selection
# =========================

def sheet_looks_standard(excel_path: Path, sheet_name: str) -> bool:
    try:
        df = pd.read_excel(excel_path, sheet_name=sheet_name, nrows=5)
        columns = [clean_text(col).lower() for col in df.columns]

        standard_keywords = [
            "check description",
            "description",
            "audit check",
            "requirement",
            "procedure",
            "check",
        ]

        return any(col in standard_keywords for col in columns)

    except Exception:
        return False


def load_all_audit_checks(excel_path):
    excel_path = Path(excel_path)

    load_errors = []
    all_rows = []

    if not excel_path.exists():
        return pd.DataFrame(), [f"Excel file not found: {excel_path}"]

    try:
        excel_file = pd.ExcelFile(excel_path)
    except Exception as e:
        return pd.DataFrame(), [f"Cannot open Excel file: {excel_path}. Error: {e}"]

    for sheet_name in excel_file.sheet_names:
        clean_sheet = clean_text(sheet_name)

        if not clean_sheet:
            continue

        if clean_sheet.startswith("~$"):
            continue

        try:
            if sheet_looks_standard(excel_path, sheet_name):
                sheet_rows = parse_standard_sheet(excel_path, sheet_name)
            else:
                sheet_rows = parse_matrix_sheet(excel_path, sheet_name)

            all_rows.extend(sheet_rows)

        except Exception as e:
            load_errors.append(f"Sheet '{sheet_name}' could not be loaded: {e}")

    if not all_rows:
        return pd.DataFrame(), load_errors

    result_df = pd.DataFrame(all_rows)

    expected_columns = [
        "Module",
        "Sub Module",
        "Check Number",
        "Check Description",
        "Check Key",
    ]

    for col in expected_columns:
        if col not in result_df.columns:
            result_df[col] = ""

    result_df = result_df[expected_columns]

    result_df = result_df[
        result_df["Check Description"].fillna("").astype(str).str.strip() != ""
    ].copy()

    result_df = result_df.drop_duplicates(subset=["Check Key"]).reset_index(drop=True)

    return result_df, load_errors