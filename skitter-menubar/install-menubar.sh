#!/usr/bin/env bash
set -euo pipefail

APP_NAME="SkitterMenuBar"
BUNDLE_ID="io.skitter.menubar"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_BUNDLE="${HOME}/Applications/${APP_NAME}.app"
APP_EXECUTABLE="${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"
INFO_PLIST="${APP_BUNDLE}/Contents/Info.plist"
LAUNCH_AGENT="${HOME}/Library/LaunchAgents/${BUNDLE_ID}.plist"
LOG_DIR="${HOME}/Library/Logs/${APP_NAME}"
LAUNCH_LABEL="${BUNDLE_ID}"
GUI_DOMAIN="gui/$(id -u)"
MODE="${1:-install}"

print_usage() {
  cat <<'EOF'
Usage:
  ./install-menubar.sh [install|uninstall|status]

Commands:
  install    Build release binary, install/update app bundle, enable autostart, and start now.
  uninstall  Remove launch agent and app bundle.
  status     Show launchd and install status.
EOF
}

build_release() {
  echo "[1/4] Building release binary..."
  swift build -c release --package-path "${PROJECT_DIR}"
}

install_app_bundle() {
  local release_bin="${PROJECT_DIR}/.build/release/${APP_NAME}"
  if [[ ! -x "${release_bin}" ]]; then
    echo "Release binary not found: ${release_bin}" >&2
    exit 1
  fi

  echo "[2/4] Installing app bundle at ${APP_BUNDLE}..."
  mkdir -p "${APP_BUNDLE}/Contents/MacOS"
  cp "${release_bin}" "${APP_EXECUTABLE}"
  chmod +x "${APP_EXECUTABLE}"

  cat > "${INFO_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
  <key>CFBundleExecutable</key><string>${APP_NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Skitter uses the microphone to transcribe your voice into chat text.</string>
</dict>
</plist>
EOF

  if command -v /usr/bin/codesign >/dev/null 2>&1; then
    /usr/bin/codesign --force --deep --sign - "${APP_BUNDLE}" >/dev/null 2>&1 || true
  fi
}

write_launch_agent() {
  echo "[3/4] Writing launch agent ${LAUNCH_AGENT}..."
  mkdir -p "${HOME}/Library/LaunchAgents" "${LOG_DIR}"
  cat > "${LAUNCH_AGENT}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LAUNCH_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${APP_EXECUTABLE}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>${LOG_DIR}/stdout.log</string>
  <key>StandardErrorPath</key><string>${LOG_DIR}/stderr.log</string>
</dict>
</plist>
EOF
}

enable_and_start() {
  echo "[4/4] Enabling and starting launch agent..."
  /bin/launchctl bootout "${GUI_DOMAIN}/${LAUNCH_LABEL}" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "${GUI_DOMAIN}" "${LAUNCH_AGENT}"
  /bin/launchctl enable "${GUI_DOMAIN}/${LAUNCH_LABEL}" >/dev/null 2>&1 || true
  /bin/launchctl kickstart -k "${GUI_DOMAIN}/${LAUNCH_LABEL}" >/dev/null 2>&1 || true
}

uninstall_all() {
  echo "Removing launch agent and app bundle..."
  /bin/launchctl bootout "${GUI_DOMAIN}/${LAUNCH_LABEL}" >/dev/null 2>&1 || true
  rm -f "${LAUNCH_AGENT}"
  rm -rf "${APP_BUNDLE}"
  echo "Done."
}

show_status() {
  echo "App bundle: ${APP_BUNDLE}"
  if [[ -x "${APP_EXECUTABLE}" ]]; then
    echo "  installed: yes"
  else
    echo "  installed: no"
  fi

  echo "Launch agent: ${LAUNCH_AGENT}"
  if [[ -f "${LAUNCH_AGENT}" ]]; then
    echo "  present: yes"
  else
    echo "  present: no"
  fi

  if /bin/launchctl print "${GUI_DOMAIN}/${LAUNCH_LABEL}" >/dev/null 2>&1; then
    echo "  launchd: running/loaded"
  else
    echo "  launchd: not loaded"
  fi
}

case "${MODE}" in
  install)
    build_release
    install_app_bundle
    write_launch_agent
    enable_and_start
    echo "Installed and started ${APP_NAME}."
    ;;
  uninstall)
    uninstall_all
    ;;
  status)
    show_status
    ;;
  *)
    print_usage
    exit 2
    ;;
esac
