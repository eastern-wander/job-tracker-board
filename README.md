# Tracker Board

Local job discovery, evidence review, CV planning and manual application tracking. No automated submission. Match scores describe relevance, not work authorization or hiring probability. Web3/Crypto employers and jobs remain excluded.

## Try with fake data

Use Python 3.11+ and an isolated virtual environment:

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python fixture_demo.py
    python app.py --no-scheduler --port 8137

Open http://127.0.0.1:8137. The demo creates invented profile and jobs locally. Model calls and email integration are disabled. Discovery returns five fake records without querying employers. Repeated discovery and CV reconciliation are idempotent. The mock CV is a one-page TEST ONLY PDF validated in memory, not a usable tailored application document.

## Configure your own workspace

Start from a fresh directory, copy runtime.example.json to runtime.local.json and supply your own resume PDF and matching DOCX. Relative paths resolve from the project, not the launch directory. The current parser expects SUMMARY, EXPERIENCE and SKILLS sections and bullet-based experience; the template renderer requires a compatible original DOCX. Arbitrary resume layouts are not yet supported.

Settings controls countries (Canada, United States, Japan, UAE, UK), priority cities, roles, match thresholds, original-publication freshness in hours, local daily time and IANA timezone. Employer feed boards start empty in this export: configure supported Greenhouse/Lever/Ashby public sources or manually import permitted job links. Sources unavailable or blocked are reported. This is not comprehensive job-market coverage. Unknown original publication times remain unknown; platform update dates are not substituted.

Run python app.py to enable its in-process scheduler. The app process must remain running and the computer awake. No service installer is included. It makes at most one bounded recovery attempt before today's slot for yesterday's missed/failed run, not a historical backfill. Failures can retry up to three times ten minutes apart. Receipt-day reporting uses UTC independently of the configurable schedule timezone. Default schedule is 09:00 UTC with no priority cities; change these example defaults for your own use.

## CV and model boundary

Automatic CV planning is preview-only, keyed by job/JD, source CV, template and policy version. Known hard failures, exclusions and prior/uncertain submissions are blocked; unknown eligibility stays unverified. Daily caps apply to fixture generation. The CV-only consumer is implemented but disabled by default. It requires separately verified account/endpoint, data and cost authorization, plus explicit opt-in. See INSTALLATION.md.

Existing explicit CV/CL actions use a locally installed Codex CLI found on PATH with your own authenticated account. They are blocked unless model_calls_enabled is true and fixture_mode is false. Verify cost, account access and privacy consent yourself before enabling; doing so transmits job and resume evidence to your model provider. No credentials are included. Cover-letter revision is available on demand. One-page and factual checks can reject output; human review is always required. Optional confirmed_facts.json may define facts with fact_id/canonical_english and metric_rules with match/required/forbidden regexes; no real personal assertions are shipped.

Manual employer handoff is followed by explicit submitted/unknown/receipt recording. A browser opening, material readiness or sandbox simulation never counts as a submitted application.

## Offline validation

    python -B -m unittest test_product test_consumer test_freshness test_application_day test_assisted_apply
    python -B smoke_fixture.py
    python -B smoke_consumer.py

The private baseline comparison test is skipped in this clean export. Smoke tests launch only a loopback fixture server, discover twice, validate mock queue behavior and restart the process with persistent fake state. They do not contact job/model services.

## Limitations and licensing

Not a general resume parser or unattended cloud service. The live CV consumer has only been exercised with fake inputs and model stubs; no paid live call was made. Existing specialized views remain available so no records are hidden or removed. Keep private data outside version control; .gitignore is a convenience, not a security boundary.

Licensed under MIT; see LICENSE. Third-party packages retain their own licenses; see THIRD_PARTY.md. This repository starts with one independent initial commit.

Detailed setup, opt-in requirements, tested/untested boundaries: [INSTALLATION.md](INSTALLATION.md).

Public-source configuration: Greenhouse board tokens can be configured directly. Lever and Ashby require explicit operator-maintained token-to-employer mappings in discovery.py before enabling their tokens in Settings; these allowlists ship empty. No employer identity is automatically treated as traditional industry. Country/city names in recognition rules and fake tests describe supported geography, not a user's selected destinations.
