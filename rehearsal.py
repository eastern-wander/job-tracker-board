"""Resumable local test-form rehearsal. No external browsing or submission."""
import json

from auto_apply import application_blockers, prior_application
from core import now, stamp
from manual_workflow import job_row

EVENT = "Dry Run checkpoint"
STEPS = ("Browser and access", "Dropdown and address", "CV upload", "Test receipt")
PREFLIGHT = {
    "browser": "Browser connection unavailable",
    "access": "Test page inaccessible",
    "login": "Login expired",
    "captcha": "CAPTCHA displayed",
    "registration": "Complex registration required",
    "overlay": "Extension sidebar covers the lower-right Continue button",
}


def checkpoint(store, job_id, observation):
    job = job_row(store, job_id)
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        if application_blockers(job, now().date()) or prior_application(c, job):
            raise ValueError("Resolve the application blockers before starting a Dry Run.")
        last = c.execute("SELECT detail FROM events WHERE job=? AND kind=? ORDER BY rowid DESC LIMIT 1",
                         (job_id, EVENT)).fetchone()
        previous = json.loads(last[0]) if last else {}
        index = previous.get("next_index", 0)
        if index == len(STEPS):
            return previous
        if observation.get("step") != STEPS[index]:
            raise ValueError("Reopen the Dry Run and resume from its saved step.")
        problem = None
        if index == 0:
            for field, message in PREFLIGHT.items():
                if observation.get(field) is not True:
                    problem = message
                    break
        elif index == 1:
            if observation.get("country") != job["country"] or observation.get("address") != "Test address":
                problem = "The test form did not retain the selected country or address."
        elif index == 2:
            if observation.get("filename") != "fixture-cv.pdf" or observation.get("upload_status") != "accepted":
                problem = "The test form did not confirm the expected filename and upload status."
        elif observation.get("receipt") != "LOCAL-TEST-RECEIPT":
            problem = "Test submission outcome unknown. Check the simulated receipt before continuing."
        next_index = index if problem else index + 1
        remedies = ("Resolve the listed browser or access issue and retry preflight.",
                    "Select both options again and verify the saved values.",
                    "Retry the fixture upload and verify its displayed filename and status.",
                    "Inspect the simulated confirmation before retrying the receipt check.")
        record = dict(job=job_id, source=job["source"] or "Manual", step=STEPS[index], time=stamp(),
                      message=problem or "Local test passed", next_index=next_index,
                      next_action=remedies[index] if problem else STEPS[next_index] if next_index < len(STEPS) else "Review test log",
                      state="Manual action required" if problem else "Rehearsal complete" if next_index == len(STEPS)
                      else "Ready to rehearse")
        store.event(c, job_id, EVENT, json.dumps(record))
    return record
