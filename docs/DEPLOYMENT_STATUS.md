# Deployment status — 2026-10-14

**NOT DEPLOYED. NOT VERIFIED LIVE.**

Target confirmed via Hostinger read-only API:
- VPS 1282458, srv1282458.hstgr.cloud
- Ubuntu 24.04, running, IPv4 76.13.21.67
- Deployment scope: /opt/rizpram-fitness-bot and REPIT container only

Actual access attempt from the execution environment:
    ssh: connect to host 76.13.21.67 port 22: Permission denied

This is a connection failure before an SSH authentication/session was established, not proof of an incorrect server password. Local SSH agent unavailable; local .ssh contains known-host records but no key files. No password or private key was requested or saved. Hostinger Docker Manager also returned that this installed OS does not support Docker Manager. No firewall, SSH configuration, VPS or other application changes were attempted.

## What is prepared

scripts/deploy.sh is the single deployment entrypoint. It stages an immutable tested commit, builds a versioned image, runs full tests against disposable PostgreSQL without host ports, performs real Supabase TLS/schema and Telegram getMe/getWebhookInfo preflight, preserves the prior REPIT image/config, updates only the verified REPIT service, checks health and actual successful getUpdates evidence, then prompts the owner to send /start and /target. It reports VERIFIED_LIVE only after both real replies succeed. Failure triggers rollback of REPIT only. It does not run migrations or install/upgrade host packages.

Use the exact passing PR head SHA:
    sudo bash scripts/deploy.sh <40-character-tested-commit-SHA>

Prerequisites placed privately on the server:
- /opt/rizpram-fitness-bot/.env, root-owned mode 600 or 400
- /opt/rizpram-fitness-bot/supabase-ca.crt, authorized project's database CA
- Token/allowed ID and direct or session-pooler URI for lzfrfpokshfrbnbaiuqo only
- Docker/Compose, curl, Python 3.10+, realpath, flock already installed
- Public repository download access (private repository support requires secure source transfer first)

## Remaining blocker

A working authorized SSH session with TCP access to 76.13.21.67:22 and a root or sudo-capable identity is required. Do not change firewall automatically. Existing host fingerprint must be verified when establishing SSH. Credentials stay outside Git and chat.

Live database TLS, Telegram polling and command replies remain untested because no server session was available. CI/unit/disposable DB success does not establish production readiness of the private server credentials. This report must be updated after a real rollout.


Automated validation before adding the version lock: 33 tests, full Docker build, Compose validation, deployment Bash syntax and dependency audit passed in CI run 38573445723. Runtime lock and isolated deployment guard/rollback simulations are being revalidated in the next PR run. These simulations use fake Docker inside a disposable container without the Docker socket; they do not claim a real rollout.
