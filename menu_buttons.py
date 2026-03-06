"""
menu_buttons.py — run with: sudo python3 menu_buttons.py
Navigate the menu using physical GPIO buttons.

  A  (GPIO5,  Pin 29) → next item
  B  (GPIO6,  Pin 31) → select item

Each button wired between its GPIO pin and GND (internal pull-up used).
"""
import logging, sys, signal, time, subprocess
import RPi.GPIO as GPIO

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

from menu_demo import MENU_ITEMS
from display.menu import ST7789Driver, Menu

# ── Button pins ───────────────────────────────────────────────────────────────
PIN_A    = 5    # next item
PIN_B    = 27   # select

DEBOUNCE_S = 0.2

ALL_PINS = (PIN_A, PIN_B)

# ── GPIO setup ────────────────────────────────────────────────────────────────
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for pin in ALL_PINS:
    try:
        GPIO.cleanup(pin)
    except Exception:
        pass
for pin in ALL_PINS:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# ── Display + menu ────────────────────────────────────────────────────────────
driver = ST7789Driver()
menu   = Menu(MENU_ITEMS, title="SLB")

# Pre-instantiate modes so in-session state is preserved between visits
_modes = {label: cls() for label, cls in MENU_ITEMS.items()}

def _shutdown(sig, frame):
    GPIO.cleanup()
    driver.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)

def _get_network() -> str:
    try:
        r = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,DEVICE", "con", "show", "--active"],
            capture_output=True, text=True, timeout=3,
        )
        for line in r.stdout.splitlines():
            name, _, dev = line.partition(":")
            if dev.strip() == "wlan0":
                return name.strip()
    except Exception:
        pass
    return ""

menu.network = _get_network()
menu.render(driver)
log.info("Menu ready — A: next, B: select")

# ── Polling loop ──────────────────────────────────────────────────────────────
prev       = {pin: GPIO.HIGH for pin in ALL_PINS}
last_t     = {pin: 0.0       for pin in ALL_PINS}
last_net_t = 0.0
NET_INTERVAL = 5.0

try:
    while True:
        now = time.monotonic()

        # Refresh network name in header
        if now - last_net_t >= NET_INTERVAL:
            last_net_t = now
            new_net = _get_network()
            if new_net != menu.network:
                menu.network = new_net
                menu.render(driver)

        for pin in ALL_PINS:
            state = GPIO.input(pin)
            if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                if now - last_t[pin] >= DEBOUNCE_S:
                    last_t[pin] = now
                    if pin == PIN_A:
                        menu.down()
                        menu.render(driver)
                        log.info("NEXT → %s", menu.select()[0])
                    elif pin == PIN_B:
                        label, _ = menu.select()
                        log.info("SELECT → %s", label)
                        _modes[label].run(driver)
                        menu.render(driver)
                        log.info("Returned to menu")
            prev[pin] = state
        time.sleep(0.02)
finally:
    GPIO.cleanup()
    driver.close()
