from datetime import datetime

import pandas as pd

from app.core.errors import AppError


def relative_date_range(period: str, reference: datetime | pd.Timestamp | None = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    now = pd.Timestamp(reference or datetime.now()).normalize()
    if now.tzinfo is not None:
        now = now.tz_localize(None)
    day = pd.Timedelta(days=1)
    if period == "today": return now, now + day
    if period == "yesterday": return now - day, now
    week = now - pd.Timedelta(days=now.weekday())
    if period == "this_week": return week, week + pd.Timedelta(days=7)
    if period == "previous_week": return week - pd.Timedelta(days=7), week
    month = now.to_period("M").start_time
    if period == "this_month": return month, month + pd.offsets.MonthBegin(1)
    if period == "previous_month": return month - pd.offsets.MonthBegin(1), month
    for count in (3, 6, 12):
        if period == f"last_{count}_months": return month - pd.offsets.MonthBegin(count - 1), now + day
    quarter = now.to_period("Q").start_time
    if period == "this_quarter": return quarter, quarter + pd.offsets.QuarterBegin(startingMonth=quarter.month)
    if period == "previous_quarter": return quarter - pd.DateOffset(months=3), quarter
    year = pd.Timestamp(year=now.year, month=1, day=1)
    if period == "this_year": return year, pd.Timestamp(year=now.year + 1, month=1, day=1)
    if period == "previous_year": return pd.Timestamp(year=now.year - 1, month=1, day=1), year
    raise AppError("Unsupported relative date period.", "INVALID_DATE_FILTER")
