"""
Render the menu and auto-scroll through all items so you can see it in action.
Run with:  sudo python3 menu_show.py
Kill with: Ctrl-C
"""
import time
import signal
from menu_demo import MENU_ITEMS
from display.menu import ST7789Driver, Menu

driver = ST7789Driver()
menu   = Menu(MENU_ITEMS, title="SETTINGS")

def _cleanup(sig, frame):
    driver.close()
    raise SystemExit(0)

signal.signal(signal.SIGTERM, _cleanup)

# Render initial state
menu.render(driver)
time.sleep(1.5)

try:
    while True:
        # Scroll all the way down
        while menu.down():
            menu.render(driver)
            time.sleep(0.4)

        time.sleep(1.0)

        # Scroll all the way back up
        while menu.up():
            menu.render(driver)
            time.sleep(0.4)

        time.sleep(1.0)

finally:
    driver.close()
