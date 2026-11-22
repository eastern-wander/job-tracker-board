"""User settings for discovery; relevance never grants eligibility."""
from zoneinfo import ZoneInfo
import datetime as dt

COUNTRIES = ("Canada", "United States", "Japan", "UAE", "UK")
DEFAULTS = {
    "timezone": "UTC",
    "enabled_countries": list(COUNTRIES),
    "fresh_hours": 72,
    "cv_queue_threshold": 80,
    "cv_queue_daily_limit": 5,
    "cv_queue_enabled": True,
    "cv_queue_mode": "Preview",
    "priority_locations": [],
}

def validate(values):
    ZoneInfo(values["timezone"])
    countries = values["enabled_countries"]
    if not isinstance(countries, list) or not countries or any(c not in COUNTRIES for c in countries):
        raise ValueError("Choose at least one supported country.")
    for key, low, high in (("fresh_hours",1,720),("cv_queue_threshold",0,100),("cv_queue_daily_limit",0,20)):
        if type(values[key]) is not int or not low <= values[key] <= high:
            raise ValueError("Invalid " + key)
    if type(values["cv_queue_enabled"]) is not bool or values["cv_queue_mode"] != "Preview":
        raise ValueError("Automatic CV queue is preview-only until live generation is separately verified.")
    if not isinstance(values["priority_locations"],list) or any(not isinstance(x,str) or len(x)>100 for x in values["priority_locations"]):
        raise ValueError("Invalid priority locations.")
    return values

def local_clock(settings, instant):
    return instant.astimezone(ZoneInfo(settings.get("timezone","UTC")))

def run_day(created, settings):
    value=dt.datetime.fromisoformat(created)
    return local_clock(settings,value).date().isoformat()

def relevant_run_health(history, settings, instant):
    local=local_clock(settings,instant)
    day=local.date().isoformat()
    runs=[r for r in history if r["kind"] in {"Scheduled","Recovery","Catch-up"}]
    today=[r for r in runs if run_day(r["created"],settings)==day]
    today.sort(key=lambda r:r["created"],reverse=True)
    latest=today[0] if today else None
    success=next((r for r in sorted(runs,key=lambda r:r["created"],reverse=True)
                  if not r["result"].get("errors") and not r["result"].get("running")),None)
    stale=success is None or (instant-dt.datetime.fromisoformat(success["created"])).total_seconds()>36*3600
    state=("running" if latest and latest["result"].get("running") else
           "failed" if latest and latest["result"].get("errors") else
           "done" if latest else "missing" if local.strftime("%H:%M")>=settings["schedule"] else "scheduled")
    return {"state":state,"stale":stale,"today":day,"timezone":settings["timezone"],
            "last_attempt":latest["created"] if latest else None,
            "last_success":success["created"] if success else None}
