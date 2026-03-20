import datetime as dt


def _parse_date_flexible(value):
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value

    value_str = str(value).strip()
    if not value_str:
        return None

    value_str = value_str[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(value_str, fmt).date()
        except ValueError:
            continue

    try:
        return dt.date.fromisoformat(value_str)
    except Exception:
        return None


def _is_in_window(candidate_date, start_date, end_date):
    return bool(candidate_date and start_date <= candidate_date <= end_date)


def _normalize_maintenance_type(value):
    mt = (value or "").strip().lower()
    if mt.startswith("prevent"):
        return "preventivo"
    if mt.startswith("correct"):
        return "correctivo"
    return "otro"


def _safe_duration_hours(work_order):
    try:
        real_h = float(work_order.real_duration or 0)
    except Exception:
        real_h = 0.0

    if real_h > 0:
        return real_h

    try:
        est_h = float(work_order.estimated_duration or 0)
    except Exception:
        est_h = 0.0

    return max(est_h, 0.0)
