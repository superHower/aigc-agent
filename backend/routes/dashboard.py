from datetime import date
from typing import Literal

from fastapi import APIRouter, Query, Request

from backend.services.dashboard import dashboard_stats
from backend.services.access import current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(
    request: Request,
    period: Literal["day", "week", "month"] = "week",
    selected_date: date = Query(default_factory=date.today),
    timezone_offset: int = Query(default=0, ge=-840, le=840),
):
    user = current_user(request)
    return dashboard_stats(request.app.state.store, period, selected_date, timezone_offset, user["id"] if user["role"] != "admin" else None)
