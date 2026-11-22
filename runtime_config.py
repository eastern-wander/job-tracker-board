"""Local path configuration. No credentials or network access."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("TRACKER_RUNTIME_CONFIG", str(ROOT / "runtime.local.json"))).expanduser()

def config():
    if not CONFIG.exists():
        return {}
    value = json.loads(CONFIG.read_text())
    if not isinstance(value, dict):
        raise ValueError("runtime.local.json must be an object")
    return value

def path(key, default):
    value = Path(os.environ.get("TRACKER_" + key.upper(), str(config().get(key, default)))).expanduser()
    return value if value.is_absolute() else ROOT / value

def data_dir():
    return path("data_dir", "data")

def resume_pdf():
    return path("resume_pdf", "data/profile/main.pdf")

def resume_docx():
    return path("resume_docx", "data/profile/main.docx")

def facts_file():
    return path("facts_file", "data/profile/confirmed_facts.json")

def model_enabled():
    return config().get("model_calls_enabled") is True and not fixture_mode()

def fixture_mode():
    return os.environ.get("TRACKER_FIXTURE_MODE") == "1" or config().get("fixture_mode") is True

def dependency_health():
    result = {}
    for label, target in (("resume_pdf", resume_pdf()), ("resume_docx", resume_docx())):
        try:
            with target.open("rb") as stream:
                readable = bool(stream.read(16))
            result[label] = {"readable": readable, "reason": "" if readable else "empty"}
        except OSError as error:
            result[label] = {"readable": False, "reason": type(error).__name__}
    return result

def worker_status():
    value=config()
    auth=value.get("cv_worker_authorization") or {}
    required=("endpoint_verified","credentials_verified","data_authorized","cost_authorized")
    enabled=(value.get("cv_worker_enabled") is True and model_enabled()
             and auth.get("provider")=="codex_cli_chatgpt" and all(auth.get(k) is True for k in required))
    return {"enabled":enabled,"state":"enabled" if enabled else "model_disabled",
            "provider":"codex_cli_chatgpt","authorization_required":list(required)}
