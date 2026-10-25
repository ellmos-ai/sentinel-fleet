# SentinelFleet static archive

Retirement snapshot: 2026-10-25. Historical baseline: e7f9c748df0ed6a677dbba38dcd725fe700fe75e.

This directory is the only deploy context for the archived public demo. It contains static fictional examples and a Python-standard-library file server. No original application, cloud SDK, model, database, credential or agent code enters the archive image. The original source outside this directory remains historical evidence.

Use the existing sentinel-fleet Cloud Run service to preserve both historical service URLs. Runtime service account must have no project permissions; mount no secrets, pass no credentials or old environment. Keep the dedicated routines-fire scheduler paused. Remove old traffic tags, verify old revision reachability and disable dedicated redeploy triggers. Provider-side verification is required separately; these source files do not prove retirement.

GET / and /blueprint serve the archive. /schaltplan redirects to /blueprint. Existing section links and extensionless deep links return the archive. /api/health identifies archived-static-demo, agent_execution=false. All other /api and /ws paths and all mutating HTTP methods return 410. UI interactions are local deterministic simulations. Browser CSP disallows network connections and form submission.

Run locally: python -B server.py, from this directory. No package installation is required. The retained Cloud Run host, stored historical data and container artifacts may still incur provider costs. Do not reactivate the former deployment as a routine fix.
