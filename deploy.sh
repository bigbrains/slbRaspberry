#!/bin/bash
# Deploy local code to Raspberry Pi and optionally launch a specific app

PI_HOST="pi@raspberrypi.local"
PI_PASS="Vladik95"
LOCAL_DIR="/Users/vladislav/Documents/slbRaspberry/"
REMOTE_DIR="~/slb/"

# ── App lookup ─────────────────────────────────────────────────────────────────
app_script() {
  case "$1" in
    ai-camera)     echo "ai_camera_demo.py" ;;
    menu)          echo "menu_show.py" ;;
    menu-buttons)  echo "menu_buttons.py" ;;
    questions)     echo "questions_demo.py" ;;
    buttons-test)  echo "buttons_demo.py" ;;
    ui-demo)       echo "ui_demo.py" ;;
    diag)          echo "diag.py" ;;
    *)             echo "" ;;
  esac
}

usage() {
  echo "Usage: ./deploy.sh [--help] [--no-restart] [--<app>]"
  echo ""
  echo "Options:"
  echo "  --help          Show this help message"
  echo "  --no-restart    Sync files only, do not restart menu_show service"
  echo ""
  echo "App shortcuts (stops service, runs app in foreground, restarts service on exit):"
  echo "  --ai-camera      ai_camera_demo.py"
  echo "  --menu           menu_show.py"
  echo "  --menu-buttons   menu_buttons.py"
  echo "  --questions      questions_demo.py"
  echo "  --buttons-test   buttons_demo.py"
  echo "  --ui-demo        ui_demo.py"
  echo "  --diag           diag.py"
  echo ""
  echo "Examples:"
  echo "  ./deploy.sh                  # sync + restart menu_show"
  echo "  ./deploy.sh --no-restart     # sync only"
  echo "  ./deploy.sh --ai-camera      # sync + run ai_camera_demo.py"
  echo "  ./deploy.sh --questions      # sync + run questions_demo.py"
  exit 0
}

# ── Parse args ─────────────────────────────────────────────────────────────────
NO_RESTART=false
APP_KEY=""

for arg in "$@"; do
  case "$arg" in
    --help|-h)
      usage
      ;;
    --no-restart)
      NO_RESTART=true
      ;;
    --*)
      key="${arg#--}"
      if [[ -n "$(app_script "$key")" ]]; then
        APP_KEY="$key"
      else
        echo "ERROR: Unknown option '$arg'"
        echo "Run ./deploy.sh --help for usage."
        exit 1
      fi
      ;;
    *)
      echo "ERROR: Unknown argument '$arg'"
      echo "Run ./deploy.sh --help for usage."
      exit 1
      ;;
  esac
done

# ── Network check ──────────────────────────────────────────────────────────────
if ! ping -c 1 -W 2 raspberrypi.local &>/dev/null; then
  echo "ERROR: Cannot reach raspberrypi.local"
  echo "Are you on the 'iPhone (Vladyslav)' network? Or is the Raspberry Pi off?"
  exit 1
fi

# ── Sync files ────────────────────────────────────────────────────────────────
echo "Deploying to Raspberry Pi..."

sshpass -p "$PI_PASS" rsync -av \
  --exclude='.venv' \
  --exclude='.git' \
  --exclude='.idea' \
  --exclude='photos/' \
  "$LOCAL_DIR" "$PI_HOST:$REMOTE_DIR"

echo "Files synced."

# ── Run app or restart service ─────────────────────────────────────────────────
if [[ -n "$APP_KEY" ]]; then
  script="$(app_script "$APP_KEY")"
  echo "Stopping menu_show service..."
  sshpass -p "$PI_PASS" ssh "$PI_HOST" "sudo systemctl stop menu_show" 2>/dev/null || true
  echo "Running $script (Ctrl+C to stop)..."
  sshpass -p "$PI_PASS" ssh -t "$PI_HOST" "cd ~/slb && sudo .venv/bin/python $script"
  echo ""
  echo "Starting menu_show service back..."
  sshpass -p "$PI_PASS" ssh "$PI_HOST" "sudo systemctl start menu_show"
  echo "Done."
elif [[ "$NO_RESTART" == false ]]; then
  echo "Restarting menu_show..."
  sshpass -p "$PI_PASS" ssh "$PI_HOST" "sudo systemctl restart menu_show"
  echo "Done. Service 'menu_show' restarted on the Pi."
else
  echo "Done. (service not restarted)"
fi
