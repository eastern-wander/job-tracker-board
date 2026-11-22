# Installation and validation walkthrough

This is a sanitized local release candidate, not the owner's personal checkout. No account, resume, job history or credentials are included. Licensed under MIT; dependency licenses remain separate.

## 1. Fake-data trial

Python 3.11+ is required. The verified local test used Python 3.12 on macOS with the listed packages already installed; a fresh pip installation on another machine is not yet verified.

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python fixture_demo.py
    python app.py --no-scheduler --port 8137

Open http://127.0.0.1:8137. All five jobs and the profile are invented. Fixture discovery never calls live job feeds. Model calls are disabled. Do not reuse this demo database for real applications.

## 2. Test

    python -B -m unittest test_product test_consumer test_freshness test_application_day test_assisted_apply
    python -B smoke_fixture.py
    python -B smoke_consumer.py

The private-baseline score comparison is skipped because it is not distributed. The original-template rendering test also skips if LibreOffice's soffice executable is absent from PATH. No test invokes a paid model; model adapters are replaced by fake plans. The template test uses the actual installed local renderer and fake profile. Both smoke scripts create fresh temporary workspaces and launch a loopback server, preserving production data.

## 3. Personal setup in a new workspace

Copy runtime.example.json to runtime.local.json. Supply your own data/profile/main.pdf and main.docx, plus optional confirmed_facts.json. The PDF and editable DOCX must represent the same facts and bullet slots. The current parser expects a compatible one-page resume with SUMMARY, EDUCATION, PROFESSIONAL EXPERIENCE and SKILLS sections; arbitrary layouts are not supported.

For one-page original-layout rendering, install a trusted LibreOffice distribution yourself and make soffice available on PATH, along with the fonts used by your template. No service or OS permission installer is included.

Settings controls countries, roles, priority cities, thresholds, original-publication freshness hours, local daily time and IANA timezone. The clean export starts with no employer feed boards enabled and does not inherit a personal employer expansion list. Add desired public Greenhouse boards, supported Lever/Ashby tokens, or permitted manual imports. Adapters and allowlists are in discovery.py. Coverage is limited to enabled sources, and a high relevance score does not establish eligibility.

Run python app.py to start the in-process scheduler. Keep the computer awake and the process running. The service is not a cloud scheduler. No success is promised on a sleeping or offline machine.

## 4. CV consumer opt-in — keep disabled until verified

The worker is implemented but defaults off. It uses the existing Codex CLI adapter, requiring a separately authenticated ChatGPT session; it is not a generic API-key or DeepSeek integration. This export finds codex on PATH. No credentials are bundled or read by installation instructions.

Before enabling, the owner must verify the actual provider/account and endpoint, permission to send resume evidence and job descriptions, and model usage/cost. runtime.example.json lists each acknowledgment as false. The worker requires model_calls_enabled and cv_worker_enabled, provider codex_cli_chatgpt, and all four authorization flags to be true. Do not toggle these merely to clear a UI warning.

The CV-only prompt omits the identity/contact block and redacts detected contact strings. Resume evidence may still be personal information, so redaction does not remove the authorization requirement. Calls are bounded by daily attempts (including failures and retries), not a guaranteed currency spend. Each job/JD/CV/template/policy key allows at most three attempts. Retries require explicit action; interrupted generation fails without silently retrying. A current version is reused. The existing combined CV/CL and on-demand CL paths remain separately guarded.

## 5. Boundaries and release status

Strict Fresh Discovery requires a verified original timestamp within the configured window. Ashby last publication, Lever creation, update dates and first sightings are not substitutes. Older high-fit jobs remain reviewable without being counted as fresh.

Tested: fake-data workflow, atomic claims and caps, version checks, restart recovery, one-page rendering with an installed local renderer, and no applications created by consumer tests.
Not tested: a paid live model call, real employer submission, a full unattended day on a different machine, arbitrary resume layouts, or comprehensive country coverage.
No applications are automatically submitted. Human review and genuine receipt tracking remain required.

Public-source configuration: Greenhouse board tokens can be configured directly. Lever and Ashby require explicit operator-maintained token-to-employer mappings in discovery.py before enabling their tokens in Settings; these allowlists ship empty. No employer identity is automatically treated as traditional industry. Country/city names in recognition rules and fake tests describe supported geography, not a user's selected destinations.
