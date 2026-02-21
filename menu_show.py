"""
Render the menu and auto-scroll through all items.

Autostart: managed by systemd (menu_show.service)
Logs:       /var/log/slb/menu_show.log
Kill:       sudo systemctl stop menu_show
"""
import logging
import os
import signal
import sys
import time

# ── Logging setup ─────────────────────────────────────────────────────────────

LOG_DIR  = "/var/log/slb"
LOG_FILE = os.path.join(LOG_DIR, "menu_show.log")

os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("Starting menu_show")

    log.debug("Importing menu modules")
    from menu_demo import MENU_ITEMS
    from display.menu import ST7789Driver, Menu

    log.debug("Initialising ST7789 driver")
    driver = ST7789Driver()
    log.info("Display driver ready")

    menu = Menu(MENU_ITEMS, title="SETTINGS")
    log.info("Menu created with %d items, %d visible at once",
             len(MENU_ITEMS), menu.visible)

    def _shutdown(sig, frame):
        log.info("Received signal %s — shutting down", sig)
        driver.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    log.debug("Rendering initial frame")
    menu.render(driver)
    log.info("Menu rendered — starting auto-scroll loop")
    time.sleep(1.5)

    while True:
        log.debug("Scrolling down")
        while menu.down():
            menu.render(driver)
            log.debug("Selected: %d / %s", menu.selected, menu.select()[0])
            time.sleep(0.4)

        log.debug("Bottom reached — pausing")
        time.sleep(1.0)

        log.debug("Scrolling up")
        while menu.up():
            menu.render(driver)
            log.debug("Selected: %d / %s", menu.selected, menu.select()[0])
            time.sleep(0.4)

        log.debug("Top reached — pausing")
        time.sleep(1.0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Unhandled exception — process will exit")
        sys.exit(1)
