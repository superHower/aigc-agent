from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from backend.db.task_store import TaskStore


def dashboard_stats(store: TaskStore, period: str, selected: date, offset: int, owner_id: str | None = None) -> dict:
    """Aggregate task cohorts; offset uses JavaScript's getTimezoneOffset convention."""
    local_zone = timezone(timedelta(minutes=-offset))
    if period == "day":
        first = selected
        last = first + timedelta(days=1)
        bucket_count = 24
    elif period == "week":
        first = selected - timedelta(days=selected.weekday())
        last = first + timedelta(days=7)
        bucket_count = 7
    else:
        first = selected.replace(day=1)
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        bucket_count = (last - first).days
    start = datetime.combine(first, time(), local_zone)
    end = datetime.combine(last, time(), local_zone)
    previous_start = start - (end - start)

    with store._connect() as connection:
        connection.execute("BEGIN")
        # Summarize all jobs per task in SQL; no prompts, paths, or credentials are read.
        rows = connection.execute("""
            SELECT t.id, t.status, t.created_at, t.auto_retry_count,
                   COUNT(j.id) AS steps,
                   SUM(CASE WHEN j.step NOT LIKE 'text_%' AND j.step NOT LIKE 'logo_%' THEN 1 ELSE 0 END) AS images,
                   SUM(CASE WHEN j.step NOT LIKE 'text_%' AND j.step NOT LIKE 'logo_%' AND j.status = 'done' THEN 1 ELSE 0 END) AS done,
                   SUM(CASE WHEN j.step NOT LIKE 'text_%' AND j.step NOT LIKE 'logo_%' AND j.status = 'failed' THEN 1 ELSE 0 END) AS failed,
                   SUM(CASE WHEN j.step NOT LIKE 'text_%' AND j.step NOT LIKE 'logo_%' AND j.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
                   SUM(CASE WHEN j.step NOT LIKE 'text_%' AND j.step NOT LIKE 'logo_%' AND j.status IN ('pending', 'processing') THEN 1 ELSE 0 END) AS active
            FROM tasks t LEFT JOIN jobs j ON j.task_id = t.id
            WHERE julianday(t.created_at) >= julianday(?) AND julianday(t.created_at) < julianday(?) AND (CAST(? AS TEXT) IS NULL OR t.owner_id = ?)
            GROUP BY t.id
            ORDER BY t.created_at DESC
        """, (previous_start.isoformat(), end.isoformat(), owner_id, owner_id)).fetchall()
        channels = connection.execute("""
            SELECT COALESCE(j.channel_name, '未分配渠道') AS name, COUNT(*) AS total,
                   SUM(j.status = 'done') AS done, SUM(j.status = 'failed') AS failed
            FROM jobs j JOIN tasks t ON t.id = j.task_id
            WHERE julianday(t.created_at) >= julianday(?) AND julianday(t.created_at) < julianday(?) AND (CAST(? AS TEXT) IS NULL OR t.owner_id = ?)
              AND j.step NOT LIKE 'text_%' AND j.step NOT LIKE 'logo_%'
            GROUP BY COALESCE(j.channel_name, '未分配渠道')
            ORDER BY done DESC, total DESC, name
        """, (start.isoformat(), end.isoformat(), owner_id, owner_id)).fetchall()

    def summary(items):
        result = {key: sum(row[key] or 0 for row in items) for key in ("images", "done", "failed", "cancelled", "active", "steps")}
        result["tasks"] = len(items)
        result["active_tasks"] = sum(row["status"] in {"queued", "running", "cancelling"} for row in items)
        result["retried_tasks"] = sum(row["auto_retry_count"] > 0 for row in items)
        finished = result["done"] + result["failed"]
        result["success_rate"] = round(result["done"] / finished * 100, 1) if finished else None
        result["estimated_cost"] = round(result["steps"] * 0.05, 2)
        return result

    current, previous = [], []
    trend = [dict(label=f"{index:02d}:00" if period == "day" else (first + timedelta(days=index)).strftime("%m-%d"),
                  tasks=0, done=0, failed=0, active=0) for index in range(bucket_count)]
    statuses = {}
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        created = created.astimezone(local_zone)
        if created < start:
            previous.append(row)
            continue
        current.append(row)
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        index = created.hour if period == "day" else (created.date() - first).days
        bucket = trend[index]
        bucket["tasks"] += 1
        for key in ("done", "failed", "active"):
            bucket[key] += row[key] or 0

    result = {
        "period": period, "start_date": first.isoformat(), "end_date": (last - timedelta(days=1)).isoformat(),
        "previous_start_date": previous_start.date().isoformat(),
        "previous_end_date": (first - timedelta(days=1)).isoformat(),
        "summary": summary(current), "previous": summary(previous), "trend": trend,
        "task_statuses": statuses, "channels": [dict(row) for row in channels],
        "recent_tasks": [dict(id=row["id"], status=row["status"], created_at=row["created_at"],
                              images=row["images"] or 0, done=row["done"] or 0,
                              failed=row["failed"] or 0, auto_retry_count=row["auto_retry_count"]) for row in current[:6]],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if owner_id is not None:
        result['channels'] = []
        for key in ('summary', 'previous'):
            result[key]['estimated_cost'] = 0
    return result
