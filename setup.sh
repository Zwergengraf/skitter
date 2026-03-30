#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE_FILE="$SCRIPT_DIR/.env.example"
CONFIG_FILE="$SCRIPT_DIR/config.yaml"
CONFIG_EXAMPLE_FILE="$SCRIPT_DIR/config.example.yaml"
DEFAULT_ADMIN_WEB_API_BASE_URL="http://localhost:8000"
BACKUP_ROOT="$SCRIPT_DIR/backups"

log() {
  printf '%s\n' "$*"
}

info() {
  printf '[INFO] %s\n' "$*"
}

warn() {
  printf '[WARN] %s\n' "$*" >&2
}

die() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: ./setup.sh <command> [args]

Commands:
  install              Create missing config/env files, generate secrets, build and start the core stack.
  upgrade [target]     Upgrade to current branch, latest tag, or a specific tag; then rebuild/restart.
  restart              Restart the running Docker Compose services (useful after config changes).
  logs [service]       Follow Docker Compose logs (default service: api).
  backup [name]        Back up .env, config.yaml, and a PostgreSQL dump into backups/<name>.
  restore <path>       Restore .env, config.yaml, and database from a backup directory.
  uninstall            Stop the Docker Compose stack.
  status               Show repo/config status and Docker Compose service state.
  doctor               Run environment and installation checks.
  help                 Show this help text.

Upgrade targets:
  current              Pull the current branch with --ff-only.
  latest               Checkout the newest git tag if one exists; otherwise pull the current branch.
  <tag>                Checkout a specific git tag.

Examples:
  ./setup.sh install
  ./setup.sh doctor
  ./setup.sh status
  ./setup.sh restart
  ./setup.sh logs api
  ./setup.sh backup
  ./setup.sh restore backups/20260320-120000
  ./setup.sh upgrade latest
  ./setup.sh upgrade v1.2.3
  ./setup.sh uninstall
EOF
}

require_tool() {
  command -v "$1" >/dev/null 2>&1 || die "Required tool not found: $1"
}

require_docker_compose() {
  docker compose version >/dev/null 2>&1 || die "Docker Compose is required (expected: 'docker compose')."
}

require_docker_running() {
  docker info >/dev/null 2>&1 || die "Docker daemon is not running or not reachable."
}

compose() {
  docker compose "$@"
}

timestamp_now() {
  date +"%Y%m%d-%H%M%S"
}

postgres_user() {
  printf '%s\n' "${SKITTER_POSTGRES_USER:-postgres}"
}

postgres_db() {
  printf '%s\n' "${SKITTER_POSTGRES_DB:-skitter}"
}

ensure_backup_root() {
  mkdir -p "$BACKUP_ROOT"
}

wait_for_postgres() {
  local user db attempts
  user="$(postgres_user)"
  db="$(postgres_db)"
  attempts=30
  while [ "$attempts" -gt 0 ]; do
    if compose exec -T postgres pg_isready -U "$user" -d "$db" >/dev/null 2>&1; then
      return 0
    fi
    attempts=$((attempts - 1))
    sleep 1
  done
  return 1
}

get_env_value() {
  python3 - "$ENV_FILE" "$1" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
if not path.exists():
    raise SystemExit(0)

for line in path.read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        continue
    lhs, rhs = line.split("=", 1)
    if lhs.strip() != key:
        continue
    value = rhs.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    sys.stdout.write(value)
    break
PY
}

set_env_value() {
  python3 - "$ENV_FILE" "$1" "$2" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
line_value = f'{key}="{value}"'
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
updated = False
out = []
for line in lines:
    stripped = line.strip()
    if stripped.startswith(f"{key}="):
        out.append(line_value)
        updated = True
    else:
        out.append(line)
if not updated:
    out.append(line_value)
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY
}

generate_hex_secret() {
  openssl rand -hex 24
}

generate_fernet_key() {
  python3 - <<'PY'
import base64
import os

print(base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"))
PY
}

validate_fernet_key() {
  python3 - "$1" <<'PY'
import base64
import sys

key = sys.argv[1].strip()
if not key:
    raise SystemExit(1)
padding = "=" * (-len(key) % 4)
try:
    raw = base64.urlsafe_b64decode((key + padding).encode("ascii"))
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if len(raw) == 32 else 1)
PY
}

ensure_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$ENV_EXAMPLE_FILE" ]; then
      cp "$ENV_EXAMPLE_FILE" "$ENV_FILE"
      info "Created .env from .env.example."
    else
      : >"$ENV_FILE"
      info "Created empty .env."
    fi
  fi

  local api_key bootstrap_code secrets_key admin_web_api_base_url config_path
  api_key="$(get_env_value SKITTER_API_KEY)"
  bootstrap_code="$(get_env_value SKITTER_BOOTSTRAP_CODE)"
  secrets_key="$(get_env_value SKITTER_SECRETS_MASTER_KEY)"
  admin_web_api_base_url="$(get_env_value ADMIN_WEB_API_BASE_URL)"
  config_path="$(get_env_value SKITTER_CONFIG_PATH)"

  if [ -z "$config_path" ]; then
    set_env_value SKITTER_CONFIG_PATH "config.yaml"
    info "Set SKITTER_CONFIG_PATH=config.yaml in .env."
  fi
  if [ -z "$api_key" ]; then
    set_env_value SKITTER_API_KEY "$(generate_hex_secret)"
    info "Generated SKITTER_API_KEY."
  fi
  if [ -z "$bootstrap_code" ]; then
    set_env_value SKITTER_BOOTSTRAP_CODE "$(generate_hex_secret)"
    info "Generated SKITTER_BOOTSTRAP_CODE."
  fi
  if [ -z "$secrets_key" ]; then
    set_env_value SKITTER_SECRETS_MASTER_KEY "$(generate_fernet_key)"
    info "Generated SKITTER_SECRETS_MASTER_KEY (valid Fernet key)."
  elif ! validate_fernet_key "$secrets_key"; then
    die "Existing SKITTER_SECRETS_MASTER_KEY in .env is not a valid Fernet key."
  fi
  if [ -z "$admin_web_api_base_url" ]; then
    set_env_value ADMIN_WEB_API_BASE_URL "$DEFAULT_ADMIN_WEB_API_BASE_URL"
    info "Set ADMIN_WEB_API_BASE_URL=$DEFAULT_ADMIN_WEB_API_BASE_URL in .env."
  fi
}

ensure_config_file() {
  if [ -f "$CONFIG_FILE" ]; then
    return
  fi
  [ -f "$CONFIG_EXAMPLE_FILE" ] || die "Missing config example file: $CONFIG_EXAMPLE_FILE"
  cp "$CONFIG_EXAMPLE_FILE" "$CONFIG_FILE"
  info "Created config.yaml from config.example.yaml."
}

build_images() {
  info "Building Docker images (including sandbox)..."
  compose --profile sandbox build api admin-web sandbox
}

start_stack() {
  info "Starting Skitter core services..."
  compose up -d postgres api admin-web
}

print_install_summary() {
  local bootstrap_code
  bootstrap_code="$(get_env_value SKITTER_BOOTSTRAP_CODE)"
  cat <<EOF

Skitter is up.

- API: http://localhost:8000
- Admin UI: http://localhost:5173
- Config: $CONFIG_FILE
- Env: $ENV_FILE
- Bootstrap code: ${bootstrap_code:-"(not set)"}

Next steps:
1. Open the admin UI and log in with SKITTER_API_KEY from .env.
2. Review config.yaml and set your model/provider credentials.
3. If you do not want Discord, set:
   discord:
     enabled: false
4. Tail logs with: docker compose logs -f api
EOF
}

cmd_install() {
  require_tool git
  require_tool docker
  require_tool python3
  require_tool openssl
  require_docker_compose
  require_docker_running
  ensure_env_file
  ensure_config_file
  build_images
  start_stack
  print_install_summary
}

git_is_clean_for_upgrade() {
  git diff --quiet --ignore-submodules -- && git diff --cached --quiet --ignore-submodules --
}

current_branch_name() {
  git branch --show-current
}

latest_tag_name() {
  git tag --sort=-version:refname | head -n 1
}

select_upgrade_target() {
  local latest_tag current_branch choice tag_choice
  latest_tag="$(latest_tag_name)"
  current_branch="$(current_branch_name)"
  log "Select an upgrade target:"
  log "1) latest${latest_tag:+ (currently $latest_tag)}"
  log "2) current${current_branch:+ (branch $current_branch)}"
  log "3) specific tag"
  printf '> '
  read -r choice
  case "$choice" in
    1) printf 'latest\n' ;;
    2) printf 'current\n' ;;
    3)
      if [ -n "$latest_tag" ]; then
        log "Recent tags:"
        git tag --sort=-version:refname | head -n 10 | sed 's/^/  - /'
      else
        log "No git tags found; enter a tag name manually."
      fi
      printf 'Tag: '
      read -r tag_choice
      [ -n "$tag_choice" ] || die "No tag entered."
      printf '%s\n' "$tag_choice"
      ;;
    *)
      die "Invalid selection."
      ;;
  esac
}

cmd_upgrade() {
  require_tool git
  require_tool docker
  require_tool python3
  require_tool openssl
  require_docker_compose
  require_docker_running

  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "This is not a git repository."
  if ! git_is_clean_for_upgrade; then
    die "Git worktree has tracked changes. Commit or stash them before upgrading."
  fi

  local target current_branch latest_tag
  target="${1:-}"
  if [ -z "$target" ]; then
    target="$(select_upgrade_target)"
  fi

  info "Fetching git tags and remote refs..."
  git fetch --tags --prune origin

  case "$target" in
    latest)
      latest_tag="$(latest_tag_name)"
      if [ -n "$latest_tag" ]; then
        info "Checking out latest tag: $latest_tag"
        git checkout "$latest_tag"
      else
        current_branch="$(current_branch_name)"
        [ -n "$current_branch" ] || die "No tags found and not currently on a branch."
        info "No tags found; pulling current branch: $current_branch"
        git pull --ff-only origin "$current_branch"
      fi
      ;;
    current)
      current_branch="$(current_branch_name)"
      [ -n "$current_branch" ] || die "Detached HEAD; specify a tag or checkout a branch first."
      info "Pulling current branch: $current_branch"
      git pull --ff-only origin "$current_branch"
      ;;
    *)
      git rev-parse -q --verify "refs/tags/$target" >/dev/null 2>&1 || die "Tag not found: $target"
      info "Checking out tag: $target"
      git checkout "$target"
      ;;
  esac

  ensure_env_file
  ensure_config_file
  build_images
  start_stack
  print_install_summary
}

cmd_uninstall() {
  require_tool docker
  require_docker_compose
  if ! docker info >/dev/null 2>&1; then
    warn "Docker daemon is not reachable; cannot stop compose services cleanly."
    exit 1
  fi
  info "Stopping Skitter services..."
  compose down
  info "Skitter services stopped."
}

cmd_restart() {
  require_tool docker
  require_docker_compose
  require_docker_running
  info "Restarting Skitter services..."
  compose restart postgres api admin-web
  info "Skitter services restarted."
}

cmd_logs() {
  require_tool docker
  require_docker_compose
  require_docker_running
  local service="${1:-api}"
  info "Following logs for service: $service"
  compose logs -f "$service"
}

cmd_backup() {
  require_tool docker
  require_docker_compose
  require_docker_running

  local backup_name backup_dir user db git_ref
  backup_name="${1:-$(timestamp_now)}"
  backup_dir="$BACKUP_ROOT/$backup_name"
  user="$(postgres_user)"
  db="$(postgres_db)"
  ensure_backup_root

  [ ! -e "$backup_dir" ] || die "Backup target already exists: $backup_dir"
  mkdir -p "$backup_dir"

  if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "$backup_dir/.env"
  fi
  if [ -f "$CONFIG_FILE" ]; then
    cp "$CONFIG_FILE" "$backup_dir/config.yaml"
  fi

  info "Ensuring PostgreSQL is running for backup..."
  compose up -d postgres >/dev/null
  wait_for_postgres || die "PostgreSQL did not become ready in time."

  info "Creating database backup..."
  compose exec -T postgres pg_dump \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    -U "$user" \
    "$db" >"$backup_dir/database.sql"

  git_ref="$(git describe --tags --always --dirty 2>/dev/null || printf 'unknown')"
  cat >"$backup_dir/metadata.txt" <<EOF
created_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
git_ref=$git_ref
postgres_user=$user
postgres_db=$db
EOF

  info "Backup created at $backup_dir"
}

cmd_restore() {
  require_tool docker
  require_docker_compose
  require_docker_running

  local target backup_dir user db
  target="${1:-}"
  [ -n "$target" ] || die "Restore requires an explicit backup directory path."
  backup_dir="$target"
  [ -d "$backup_dir" ] || die "Backup directory not found: $backup_dir"
  user="$(postgres_user)"
  db="$(postgres_db)"

  info "Restoring from backup: $backup_dir"

  if [ -f "$backup_dir/.env" ]; then
    cp "$backup_dir/.env" "$ENV_FILE"
    info "Restored .env"
  else
    warn "Backup does not contain .env"
  fi

  if [ -f "$backup_dir/config.yaml" ]; then
    cp "$backup_dir/config.yaml" "$CONFIG_FILE"
    info "Restored config.yaml"
  else
    warn "Backup does not contain config.yaml"
  fi

  if [ -f "$backup_dir/database.sql" ]; then
    info "Ensuring PostgreSQL is running for restore..."
    compose up -d postgres >/dev/null
    wait_for_postgres || die "PostgreSQL did not become ready in time."
    compose stop api admin-web >/dev/null 2>&1 || true
    info "Restoring database..."
    compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$user" -d "$db" <"$backup_dir/database.sql"
    compose up -d api admin-web >/dev/null
    info "Database restored and services restarted."
  else
    warn "Backup does not contain database.sql; skipped database restore."
  fi
}

cmd_status() {
  require_tool git
  require_tool docker
  require_docker_compose

  log "Skitter status"
  log "--------------"
  log "Repo: $SCRIPT_DIR"
  log "Git ref: $(git describe --tags --always --dirty 2>/dev/null || printf 'unknown')"
  log ".env: $([ -f "$ENV_FILE" ] && printf 'present' || printf 'missing')"
  log "config.yaml: $([ -f "$CONFIG_FILE" ] && printf 'present' || printf 'missing')"
  if docker info >/dev/null 2>&1; then
    printf '\nDocker Compose services:\n'
    compose ps
  else
    warn "Docker daemon is not reachable."
  fi
}

doctor_failures=0

doctor_ok() {
  printf '[ OK ] %s\n' "$*"
}

doctor_warn() {
  printf '[WARN] %s\n' "$*"
}

doctor_fail() {
  printf '[FAIL] %s\n' "$*"
  doctor_failures=$((doctor_failures + 1))
}

doctor_check_tool() {
  if command -v "$1" >/dev/null 2>&1; then
    doctor_ok "Tool available: $1"
  else
    doctor_fail "Missing required tool: $1"
  fi
}

cmd_doctor() {
  doctor_failures=0

  log "Running Skitter doctor..."
  doctor_check_tool git
  doctor_check_tool docker
  doctor_check_tool python3
  doctor_check_tool openssl

  if docker compose version >/dev/null 2>&1; then
    doctor_ok "Docker Compose available"
  else
    doctor_fail "Docker Compose is not available via 'docker compose'"
  fi

  if docker info >/dev/null 2>&1; then
    doctor_ok "Docker daemon is reachable"
  else
    doctor_fail "Docker daemon is not reachable"
  fi

  if [ -f "$ENV_FILE" ]; then
    doctor_ok ".env exists"
    local secrets_key api_key bootstrap_code
    secrets_key="$(get_env_value SKITTER_SECRETS_MASTER_KEY)"
    api_key="$(get_env_value SKITTER_API_KEY)"
    bootstrap_code="$(get_env_value SKITTER_BOOTSTRAP_CODE)"
    if [ -n "$api_key" ]; then
      doctor_ok "SKITTER_API_KEY is set"
    else
      doctor_fail "SKITTER_API_KEY is missing or empty in .env"
    fi
    if [ -n "$bootstrap_code" ]; then
      doctor_ok "SKITTER_BOOTSTRAP_CODE is set"
    else
      doctor_fail "SKITTER_BOOTSTRAP_CODE is missing or empty in .env"
    fi
    if validate_fernet_key "$secrets_key"; then
      doctor_ok "SKITTER_SECRETS_MASTER_KEY is a valid Fernet key"
    else
      doctor_fail "SKITTER_SECRETS_MASTER_KEY is missing or invalid"
    fi
  else
    doctor_fail ".env is missing"
  fi

  if [ -f "$CONFIG_FILE" ]; then
    doctor_ok "config.yaml exists"
  else
    doctor_fail "config.yaml is missing"
  fi

  if docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    if compose config -q >/dev/null 2>&1; then
      doctor_ok "docker compose configuration is valid"
    else
      doctor_fail "docker compose configuration is invalid"
    fi
    if compose ps >/dev/null 2>&1; then
      doctor_ok "docker compose state can be read"
      compose ps
    else
      doctor_fail "docker compose state could not be read"
    fi
  fi

  if command -v curl >/dev/null 2>&1; then
    if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
      doctor_ok "API health endpoint responded"
    else
      doctor_warn "API health endpoint did not respond (stack may be stopped)"
    fi
  else
    doctor_warn "curl not found; skipped API health check"
  fi

  if [ "$doctor_failures" -gt 0 ]; then
    die "Doctor found $doctor_failures issue(s)."
  fi
  info "Doctor checks passed."
}

main() {
  local command="${1:-help}"
  case "$command" in
    install)
      shift
      cmd_install "$@"
      ;;
    upgrade)
      shift
      cmd_upgrade "$@"
      ;;
    uninstall)
      shift
      cmd_uninstall "$@"
      ;;
    restart)
      shift
      cmd_restart "$@"
      ;;
    logs)
      shift
      cmd_logs "$@"
      ;;
    backup)
      shift
      cmd_backup "$@"
      ;;
    restore)
      shift
      cmd_restore "$@"
      ;;
    status)
      shift
      cmd_status "$@"
      ;;
    doctor)
      shift
      cmd_doctor "$@"
      ;;
    help|-h|--help)
      usage
      ;;
    *)
      usage
      die "Unknown command: $command"
      ;;
  esac
}

main "$@"
