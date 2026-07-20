from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import models
from .config import ATTACHMENTS_DIR, REPORTS_DIR


def get_machine_level(score: float, fail_count: int) -> str:
    if fail_count >= 10:
        return "D - Not Approved"
    if score >= 90:
        return "A - Excellent"
    if score >= 75:
        return "B - Good"
    if score >= 60:
        return "C - Needs Improvement"
    return "D - Not Approved"


def calculate_summary(results: list[models.AuditResult]) -> dict:
    total = len(results)
    performed_results = [r for r in results if r.result or r.comment]
    performed = len(performed_results)

    pass_count = sum(1 for r in performed_results if r.result == "Pass")
    near_fail_count = sum(1 for r in performed_results if r.result == "Near Fail")
    fail_count = sum(1 for r in performed_results if r.result == "Fail")
    na_count = sum(1 for r in performed_results if r.result == "N/A")

    counted = performed - na_count
    score = round(((pass_count + near_fail_count * 0.5) / counted) * 100, 1) if counted > 0 else 0.0
    performed_percent = round((performed / total) * 100, 1) if total > 0 else 0.0

    return {
        "total": total,
        "performed": performed,
        "performed_percent": performed_percent,
        "pass": pass_count,
        "near_fail": near_fail_count,
        "fail": fail_count,
        "na": na_count,
        "score": score,
    }


def generate_audit_pdf(audit: models.Audit) -> Path:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleCustom", parent=styles["Title"], fontSize=18)
    heading_style = styles["Heading2"]
    critical_style = ParagraphStyle("Critical", parent=styles["Normal"], textColor=colors.red, fontName="Helvetica-Bold")

    folder = REPORTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    file_name = f"audit_{audit.id}_{audit.client_uuid[:8]}.pdf"
    file_path = folder / file_name

    doc = SimpleDocTemplate(str(file_path), pagesize=A4, topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    story = []

    report_title = "Machine Audit Report" if audit.audit_type != "Post Installation Audit" else "Post Installation Audit Report"
    story.append(Paragraph(report_title, title_style))
    story.append(Spacer(1, 12))

    machine = audit.machine
    detail_rows = [
        ["Field", "Value"],
        ["Audit Type", audit.audit_type],
        ["Machine Model", machine.machine_model.name if machine and machine.machine_model else ""],
        ["Serial Number", machine.serial_number if machine else ""],
        ["Customer / Site", f"{machine.customer} / {machine.site}" if machine else ""],
        ["Region", machine.region if machine else ""],
        ["Audit Date", audit.started_at.strftime("%Y-%m-%d") if audit.started_at else ""],
        ["Engineer", audit.engineer.name if audit.engineer else ""],
        ["Status", audit.status.value if hasattr(audit.status, "value") else str(audit.status)],
        ["Systems Checked", ", ".join(sorted({link.system_def.name for link in audit.systems if link.system_def}))],
    ]
    detail_table = Table(detail_rows, colWidths=[2 * inch, 4 * inch])
    detail_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3e46")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ]
        )
    )
    story.append(detail_table)
    story.append(Spacer(1, 16))

    results = list(audit.results)
    summary = calculate_summary(results)
    level = get_machine_level(summary["score"], summary["fail"])

    story.append(Paragraph("Overall Summary", heading_style))
    summary_rows = [
        ["Total", "Performed", "Performed %", "Pass", "Near Fail", "Fail", "N/A", "Score"],
        [
            summary["total"],
            summary["performed"],
            f"{summary['performed_percent']}%",
            summary["pass"],
            summary["near_fail"],
            summary["fail"],
            summary["na"],
            f"{summary['score']}%",
        ],
    ]
    summary_table = Table(summary_rows, colWidths=[0.7 * inch] * 8)
    summary_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3e46")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"<b>Overall Machine Level:</b> {level}", styles["Normal"]))
    story.append(Spacer(1, 16))

    story.append(Paragraph("Detailed Results", heading_style))

    attachments_by_result = {}
    for a in audit.attachments:
        attachments_by_result.setdefault(a.audit_result_id, []).append(a)

    def sort_key(result):
        item = result.checklist_item
        if item is None or item.sub_module is None:
            return (0, "", 0, "", 0)
        return (
            item.sub_module.system_def.order_index,
            item.sub_module.system_def.name,
            item.sub_module.order_index,
            item.sub_module.name,
            item.order_index,
        )

    sorted_results = sorted(results, key=sort_key)

    current_system = None
    current_sub_module = None
    item_number = 0

    for result in sorted_results:
        if not (result.result or result.comment):
            continue

        item = result.checklist_item
        system_name = item.sub_module.system_def.name if item and item.sub_module else "Legacy"
        sub_module_name = item.sub_module.name if item and item.sub_module else "Legacy"

        if system_name != current_system:
            story.append(Spacer(1, 10))
            story.append(Paragraph(system_name, styles["Heading2"]))
            current_system = system_name
            current_sub_module = None

        if sub_module_name != current_sub_module:
            story.append(Paragraph(sub_module_name, styles["Heading3"]))
            current_sub_module = sub_module_name
            item_number = 0

        item_number += 1

        label_style = critical_style if result.flagged_critical else styles["Normal"]
        flag_text = " [CRITICAL ISSUE]" if result.flagged_critical else ""

        text = (
            f"<b>{item_number}. {item.description}</b>{flag_text}<br/>"
            f"Result: {result.result or '(not set)'}"
        )
        if result.comment:
            text += f"<br/>Comment: {result.comment}"

        story.append(Paragraph(text, label_style))

        for attachment in attachments_by_result.get(result.id, []):
            image_path = ATTACHMENTS_DIR.parent / attachment.file_path
            if image_path.exists():
                try:
                    story.append(Image(str(image_path), width=3.2 * inch, height=2.4 * inch, kind="proportional"))
                except Exception:
                    story.append(Paragraph(f"[image could not be embedded: {attachment.file_path}]", styles["Normal"]))

        story.append(Spacer(1, 6))

    doc.build(story)
    return file_path
