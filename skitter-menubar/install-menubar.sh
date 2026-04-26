#!/usr/bin/env bash
set -euo pipefail

APP_NAME="SkitterMenuBar"
BUNDLE_ID="io.skitter.menubar"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_BUNDLE="${HOME}/Applications/${APP_NAME}.app"
APP_EXECUTABLE="${APP_BUNDLE}/Contents/MacOS/${APP_NAME}"
RESOURCES_DIR="${APP_BUNDLE}/Contents/Resources"
INFO_PLIST="${APP_BUNDLE}/Contents/Info.plist"
LAUNCH_AGENT="${HOME}/Library/LaunchAgents/${BUNDLE_ID}.plist"
LOG_DIR="${HOME}/Library/Logs/${APP_NAME}"
LAUNCH_LABEL="${BUNDLE_ID}"
GUI_DOMAIN="gui/$(id -u)"
MODE="${1:-install}"
APP_ICON_NAME="AppIcon.icns"
ICON_SCRIPT="${PROJECT_DIR}/scripts/generate_app_icon.swift"
ICON_BUILD_DIR="${PROJECT_DIR}/.build/icon-build"
ICONSET_DIR="${ICON_BUILD_DIR}/AppIcon.iconset"
ICON_SOURCE_PNG="${ICON_BUILD_DIR}/AppIcon-1024.png"
ICON_DEST_PATH="${RESOURCES_DIR}/${APP_ICON_NAME}"
CLANG_CACHE_DIR="${PROJECT_DIR}/.build/clang-module-cache"

mkdir -p "${CLANG_CACHE_DIR}"
export CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-${CLANG_CACHE_DIR}}"

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

generate_app_icon() {
  if [[ ! -f "${ICON_SCRIPT}" ]]; then
    return
  fi
  if ! command -v sips >/dev/null 2>&1 || ! command -v iconutil >/dev/null 2>&1; then
    echo "Warning: sips or iconutil missing; skipping app icon generation."
    return
  fi

  rm -rf "${ICON_BUILD_DIR}"
  mkdir -p "${ICONSET_DIR}"

  if ! swift "${ICON_SCRIPT}" "${ICON_SOURCE_PNG}"; then
    echo "Warning: app icon PNG generation failed; continuing without app icon."
    rm -rf "${ICON_BUILD_DIR}"
    return
  fi

  sips -s format png -z 16 16 "${ICON_SOURCE_PNG}" --out "${ICONSET_DIR}/icon_16x16.png" >/dev/null
  sips -s format png -z 32 32 "${ICON_SOURCE_PNG}" --out "${ICONSET_DIR}/icon_16x16@2x.png" >/dev/null
  sips -s format png -z 32 32 "${ICON_SOURCE_PNG}" --out "${ICONSET_DIR}/icon_32x32.png" >/dev/null
  sips -s format png -z 64 64 "${ICON_SOURCE_PNG}" --out "${ICONSET_DIR}/icon_32x32@2x.png" >/dev/null
  sips -s format png -z 128 128 "${ICON_SOURCE_PNG}" --out "${ICONSET_DIR}/icon_128x128.png" >/dev/null
  sips -s format png -z 256 256 "${ICON_SOURCE_PNG}" --out "${ICONSET_DIR}/icon_128x128@2x.png" >/dev/null
  sips -s format png -z 256 256 "${ICON_SOURCE_PNG}" --out "${ICONSET_DIR}/icon_256x256.png" >/dev/null
  sips -s format png -z 512 512 "${ICON_SOURCE_PNG}" --out "${ICONSET_DIR}/icon_256x256@2x.png" >/dev/null
  sips -s format png -z 512 512 "${ICON_SOURCE_PNG}" --out "${ICONSET_DIR}/icon_512x512.png" >/dev/null
  sips -s format png -z 1024 1024 "${ICON_SOURCE_PNG}" --out "${ICONSET_DIR}/icon_512x512@2x.png" >/dev/null

  if ! iconutil -c icns "${ICONSET_DIR}" -o "${ICON_DEST_PATH}"; then
    echo "Warning: iconutil failed; continuing without app icon."
  fi
  rm -rf "${ICON_BUILD_DIR}"
}

install_app_bundle() {
  local release_bin="${PROJECT_DIR}/.build/release/${APP_NAME}"
  if [[ ! -x "${release_bin}" ]]; then
    echo "Release binary not found: ${release_bin}" >&2
    exit 1
  fi

  echo "[2/4] Installing app bundle at ${APP_BUNDLE}..."
  mkdir -p "${APP_BUNDLE}/Contents/MacOS" "${RESOURCES_DIR}"
  cp "${release_bin}" "${APP_EXECUTABLE}"
  chmod +x "${APP_EXECUTABLE}"
  generate_app_icon

  cat > "${INFO_PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key><string>${BUNDLE_ID}</string>
  <key>CFBundleExecutable</key><string>${APP_NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Skitter uses the microphone to transcribe your voice into chat text.</string>
  <key>NSSpeechRecognitionUsageDescription</key><string>Skitter uses Apple Speech to transcribe your voice into chat text.</string>
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
  <key>KeepAlive</key><false/>
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
