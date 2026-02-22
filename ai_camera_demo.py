"""
ai_camera_demo.py — run with: sudo python3 ai_camera_demo.py
Takes a photo every 5 seconds, shows it on screen, saves it, and
rsyncs the photos directory to the Mac over SSH.

Mac sync destination (edit MAC_DEST to match your setup):
    oksanka@<mac-ip>:/Users/oksanka/slb_photos/
"""
import logging, sys, signal, time, subprocess

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

from display.menu import ST7789Driver
from display.ai_camera import AICamera, PHOTO_DIR

# ── Mac sync destination ───────────────────────────────────────────────────────
# Set to "user@mac-ip:/path/" — leave empty to disable sync.
MAC_DEST = "oksanka@MacBook-Air-Oksanka.local:/Users/oksanka/slb_photos/"

driver = ST7789Driver()
cam    = AICamera()

def _shutdown(sig, frame):
    driver.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)

log.info("Camera available: %s", cam.is_available())
log.info("Photos saved to:  %s", PHOTO_DIR)
log.info("Mac destination:  %s", MAC_DEST or "(disabled)")


def _sync_to_mac():
    if not MAC_DEST:
        return
    try:
        result = subprocess.run(
            ["rsync", "-az", "--no-perms",
             PHOTO_DIR + "/", MAC_DEST],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0:
            log.info("Synced photos → %s", MAC_DEST)
        else:
            log.warning("rsync failed: %s", result.stderr.decode().strip())
    except subprocess.TimeoutExpired:
        log.warning("rsync timed out")
    except FileNotFoundError:
        log.warning("rsync not found — skipping sync")


try:
    while True:
        path = cam.capture_and_display(driver)
        if path:
            _sync_to_mac()
        time.sleep(5)
finally:
    driver.close()
