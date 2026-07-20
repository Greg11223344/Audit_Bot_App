def get_completed_results(audit_results: dict) -> dict:
    completed = {}

    for key, item in audit_results.items():
        result = str(item.get("result", "")).strip()
        comment = str(item.get("comment", "")).strip()
        image_path = str(item.get("image_path", "")).strip()

        if result or comment or image_path:
            completed[key] = item

    return completed


def calculate_score_from_results(audit_results: dict) -> dict:
    completed_results = get_completed_results(audit_results)

    total = len(completed_results)
    pass_count = 0
    near_fail_count = 0
    fail_count = 0
    na_count = 0

    for item in completed_results.values():
        result = str(item.get("result", "")).strip()

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