#!/usr/bin/env bash
# Usage in authorized SSH session: sudo bash scripts/deploy.sh <tested 40-character SHA>
set -Eeuo pipefail
umask 077
BASE=/opt/rizpram-fitness-bot
PROJECT=rizpram-fitness-bot
SHA="${1:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Provide exact tested Git commit SHA."; exit 2; }
[[ "$(id -u)" == 0 ]] || { echo "Run with sudo/root in authorized SSH session."; exit 2; }
for tool in docker curl python3 realpath flock; do
    command -v "$tool" >/dev/null || { echo "Missing tool: $tool. Nothing installed automatically."; exit 2; }
done
docker compose version >/dev/null
[[ ! -L "$BASE" ]] || { echo "Deployment root must not be a symlink."; exit 2; }
[[ "$(realpath -m "$BASE")" == "$BASE" ]] || { echo "Unexpected deployment path."; exit 2; }
mkdir -p "$BASE"
[[ "$(stat -c '%u' "$BASE")" == 0 ]] || { echo "Deployment directory must belong to root."; exit 2; }
(( (8#$(stat -c '%a' "$BASE") & 0022) == 0 )) || { echo "Deployment root must not be group/world writable."; exit 2; }
[[ "$(realpath "$BASE")" == "$BASE" ]] || { echo "Unexpected deployment root."; exit 2; }
exec 9>"$BASE/.deployment.lock"
flock -n 9 || { echo "Another REPIT deployment is active."; exit 2; }
for secret in .env supabase-ca.crt; do
    [[ -f "$BASE/$secret" && ! -L "$BASE/$secret" ]] || {
        echo "Configure $BASE/$secret privately; no secrets requested or generated here."
        exit 2
    }
done
[[ "$(stat -c '%a' "$BASE/.env")" == 600 || "$(stat -c '%a' "$BASE/.env")" == 400 ]] || {
    echo ".env permissions must be 600 or 400."; exit 2
}
[[ "$(stat -c '%u' "$BASE/.env")" == 0 ]] || { echo ".env must belong to root."; exit 2; }
# Public CA certificate, not a secret: container user 10001 must read it, root must own it.
CA_MODE="$(stat -c '%a' "$BASE/supabase-ca.crt")"
[[ "$(stat -c '%u' "$BASE/supabase-ca.crt")" == 0 ]] && (( (8#$CA_MODE & 0004) && !(8#$CA_MODE & 0022) )) || {
    echo "supabase-ca.crt must be root-owned mode 644 or 444 (container runs as non-root)."; exit 2
}
grep -q -- '-----BEGIN CERTIFICATE-----' "$BASE/supabase-ca.crt" || {
    echo "supabase-ca.crt is not a PEM certificate; download the project's CA from Supabase."; exit 2
}
RUN="$(date -u +%Y%m%dT%H%M%SZ)-$$"
SOURCE="$BASE/releases/$SHA-$RUN"
REPORT="$BASE/deployment-$RUN.log"
[[ ! -L "$BASE/releases" ]] || { echo "Release directory must not be a symlink."; exit 2; }
mkdir -p "$BASE/releases"
[[ "$(realpath "$BASE/releases")" == "$BASE/releases" ]] || { echo "Unsafe releases path."; exit 2; }
[[ ! -e "$SOURCE" ]] || { echo "Staging path already exists."; exit 2; }
mkdir "$SOURCE"
[[ "$(realpath "$SOURCE")" == "$BASE/releases/"* ]] || { echo "Unsafe staging path."; exit 2; }
exec > >(tee -a "$REPORT") 2>&1
echo "SOURCE_COMMIT=$SHA"
echo "Deployment root: $BASE"
echo "Existing containers (read-only):"
docker ps --format '{{.ID}} {{.Names}} {{.Status}}'
CI_DB="repit-test-$RUN"
CI_LABEL="repit-test-$RUN"
OLD_ID=""
OLD_CONFIG=""
OLD_IMAGE=""
REPLACED=0
SUCCESS=0
IMAGE="repit:$SHA"
OVERRIDE="$BASE/rollback-$RUN.yml"
compose() {
    REPIT_ENV_FILE="$BASE/.env" REPIT_CA_FILE="$BASE/supabase-ca.crt" REPIT_IMAGE="$IMAGE" \
      docker compose -p "$PROJECT" --project-directory "$SOURCE" -f "$SOURCE/docker-compose.yml" "$@"
}
cleanup() {
    local code=$?
    trap - EXIT
    if [[ "$(docker inspect --format '{{index .Config.Labels "repit.deployment-test"}}' "$CI_DB" 2>/dev/null || true)" == "$CI_LABEL" ]]; then
        docker rm -f "$CI_DB" >/dev/null || true
    fi
    if [[ "$REPLACED" == 1 && "$SUCCESS" != 1 ]]; then
        echo "Verification failed; rolling back only REPIT."
        compose stop fitness-bot >/dev/null 2>&1 || true
        if [[ -n "$OLD_IMAGE" && -f "$OLD_CONFIG" ]]; then
            REPIT_ENV_FILE="$BASE/.env" REPIT_CA_FILE="$BASE/supabase-ca.crt" REPIT_IMAGE="$OLD_IMAGE" \
              docker compose -p "$PROJECT" -f "$OLD_CONFIG" -f "$OVERRIDE" up -d --no-build --no-deps fitness-bot || {
                echo "ROLLBACK_FAILED: inspect REPIT privately; other containers not stopped."
            }
        else
            echo "No previous REPIT image; failed new service left stopped."
        fi
        echo "DEPLOYMENT_NOT_LIVE"
    elif [[ "$SUCCESS" != 1 ]]; then
        echo "DEPLOYMENT_NOT_LIVE; existing REPIT not replaced."
    fi
    echo "Sanitized report: $REPORT"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
  "https://codeload.github.com/rizpram/repit/tar.gz/$SHA" -o "$SOURCE/source.tar.gz"
python3 - "$SOURCE" <<'PY'
import pathlib, tarfile, sys
root=pathlib.Path(sys.argv[1]).resolve()
with tarfile.open(root/'source.tar.gz') as archive:
    for member in archive.getmembers():
        path=pathlib.PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not (member.isdir() or member.isfile()):
            raise SystemExit('Unsafe source archive member')
        parts=path.parts[1:]
        if not parts:
            continue
        target=root.joinpath(*parts)
        if not target.resolve().is_relative_to(root):
            raise SystemExit('Archive escapes staging')
        if member.isdir():
            target.mkdir(parents=True,exist_ok=True)
            target.chmod(0o755)
        else:
            if target.name=='.env' or (target.name.startswith('.env.') and target.name!='.env.example'):
                raise SystemExit('Source contains credentials file')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
            target.chmod(0o644)
PY
[[ "$(compose config --services)" == fitness-bot ]] || { echo "Unexpected services; refuse deployment."; exit 2; }
compose config --format json | python3 -c '
import json,sys
s=json.load(sys.stdin)["services"]["fitness-bot"]
assert not s.get("ports"), "Host ports refused"
assert not s.get("privileged"), "Privileged container refused"
assert s.get("read_only"), "Read-only filesystem required"
'  # Resolved config contains secrets: parse privately, never print it.
echo "Build before stopping existing REPIT."
compose build fitness-bot
echo "Full tests in disposable PostgreSQL; no Supabase writes."
docker run -d --name "$CI_DB" --label "repit.deployment-test=$CI_LABEL" \
  --memory 256m --pids-limit 100 --tmpfs /var/lib/postgresql/data:rw,size=128m \
  -e POSTGRES_PASSWORD=ci-only-password -e POSTGRES_DB=repit_test \
  postgres:16 -c shared_buffers=16MB -c max_connections=20 >/dev/null
ready=0
for _ in $(seq 1 30); do
    if docker exec "$CI_DB" pg_isready -U postgres >/dev/null 2>&1; then ready=1; break; fi
    sleep 2
done
[[ "$ready" == 1 ]] || { echo "Disposable test DB not ready."; exit 1; }
docker run --rm --user 0:0 --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp --network "container:$CI_DB" -v "$SOURCE:/workspace:ro" -w /workspace \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e TEST_DATABASE_URL=postgresql://postgres:ci-only-password@127.0.0.1:5432/repit_test \
  --entrypoint python "$IMAGE" -m unittest discover -s tests -v
docker rm -f "$CI_DB" >/dev/null
echo "Preflight: Supabase TLS/schema and Telegram identity, no update consumption."
compose run --rm --no-deps --entrypoint python fitness-bot -m app.verify

# Ignore leftover `compose run` one-off containers; only the service container is replaced.
mapfile -t existing < <(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" --filter "label=com.docker.compose.oneoff=False")
[[ "${#existing[@]}" -le 1 ]] || { echo "Multiple REPIT containers; manual review required."; exit 2; }
if [[ "${#existing[@]}" == 1 ]]; then
    OLD_ID="${existing[0]}"
    service="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$OLD_ID")"
    workdir="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$OLD_ID")"
    OLD_CONFIG="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$OLD_ID")"
    [[ "$service" == fitness-bot && ("$workdir" == "$BASE" || "$workdir" == "$BASE/releases/"*) ]] || {
        echo "Existing project ownership/path differs; refuse to stop."; exit 2
    }
    [[ "$OLD_CONFIG" != *,* && -f "$OLD_CONFIG" && "$(realpath "$OLD_CONFIG")" == "$BASE/"* ]] || {
        echo "Rollback config outside approved root or multiple configs; manual review required."; exit 2
    }
    OLD_IMAGE="$(docker inspect --format '{{.Image}}' "$OLD_ID")"
    docker tag "$OLD_IMAGE" "repit:rollback-$RUN"
    OLD_IMAGE="repit:rollback-$RUN"
    printf 'services:\n  fitness-bot:\n    image: %s\n' "$OLD_IMAGE" > "$OVERRIDE"
    printf 'Previous image: %s\nPrevious config: %s\n' "$OLD_IMAGE" "$OLD_CONFIG"
    REPLACED=1
    docker stop "$OLD_ID" >/dev/null
fi
REPLACED=1
compose up -d --no-build --no-deps fitness-bot
CID="$(compose ps -q fitness-bot)"
[[ -n "$CID" ]] || { echo "REPIT container missing."; exit 1; }
healthy=0
for _ in $(seq 1 36); do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$CID")"
    if [[ "$status" == healthy ]]; then healthy=1; break; fi
    [[ "$(docker inspect --format '{{.State.Running}}' "$CID")" == true ]] || break
    sleep 5
done
[[ "$healthy" == 1 ]] || { echo "Healthcheck failed."; exit 1; }
docker exec "$CID" python -m app.diagnostics
compose run --rm --no-deps --entrypoint python fitness-bot -m app.verify --notify
echo "Send /start and /target from allowed Telegram account now (3-minute window)."
verified=0
for _ in $(seq 1 36); do
    if docker exec "$CID" python -m app.diagnostics --require-commands; then verified=1; break; fi
    sleep 5
done
[[ "$verified" == 1 ]] || { echo "Real command replies not verified; rollback required."; exit 1; }
SUCCESS=1
printf '%s\n' "$SHA" > "$BASE/deployed-commit"
echo "VERIFIED_LIVE: Supabase TLS, successful getUpdates, /start and /target replies, healthy REPIT."
echo "Container: $CID"
echo "No ports, migration replay, reboot, firewall, Nginx, HestiaCP, PM2 or other container changes."
