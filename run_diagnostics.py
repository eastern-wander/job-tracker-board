"""Pure run-history diagnostics. No file, network, or application side effects."""
import datetime as dt
import json


RUN_KINDS = {"Scheduled", "Catch-up", "Recovery"}


def successful(result):
    return not result.get("running") and not result.get("errors")


def cadence_report(history, first, local, schedule, limit=30):
    """Dates describe recorded execution, not uptime or quota fulfillment."""
    end = local.date() if local.strftime("%H:%M") >= schedule else local.date() - dt.timedelta(days=1)
    relevant = [r for r in history if r["kind"] in RUN_KINDS]
    dates = [(end - dt.timedelta(days=i)).isoformat()
             for i in range(min(limit, max(0, (end - first).days + 1)))]
    missing, failed, pending = [], [], []
    for day in dates:
        attempts = [r for r in relevant if r["created"][:10] == day]
        if not attempts:
            missing.append(day)
        elif any(successful(r["result"]) for r in attempts):
            continue
        elif any(r["result"].get("running") for r in attempts):
            pending.append(day)
        else:
            failed.append(day)
    completed = [r["created"] for r in relevant if successful(r["result"])]
    return {"missing_dates": missing, "failed_dates": failed, "incomplete_dates": pending,
            "last_error_free_run": max(completed, default=None),
            "basis": "Recorded outcomes only; no proof of host uptime or target fulfillment"}


class FailureLog:
    """Bound identical outage logs; count failures without storing exception paths."""
    def __init__(self, interval=600):
        self.interval = interval
        self.signature = None
        self.last = None
        self.count = 0

    def failed(self, category, tick):
        self.count += 1
        emit = category != self.signature or self.last is None or tick - self.last >= self.interval
        self.signature = category
        if emit:
            self.last = tick
        return emit

    def recovered(self):
        count = self.count
        self.signature = self.last = None
        self.count = 0
        return count


def load_cadence(connection, first, local, schedule):
    # The UI's 30 most recent runs are insufficient when retries consume rows.
    cutoff = (local.date() - dt.timedelta(days=30)).isoformat()
    history = [{"created": dt.datetime.fromisoformat(created).astimezone(local.tzinfo).isoformat(), "kind": kind, "result": json.loads(result)}
               for created, kind, result in connection.execute(
                   "SELECT created,kind,result FROM runs WHERE kind IN ('Scheduled','Catch-up','Recovery') AND created>=?",
                   (cutoff,))]
    return cadence_report(history, first, local, schedule)
