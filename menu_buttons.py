"""
menu_buttons.py — run with: sudo python3 menu_buttons.py
Navigate the menu using physical GPIO buttons.

  UP    (GPIO17, Pin 11) → move selection up
  DOWN  (GPIO27, Pin 13) → move selection down
  LEFT  (GPIO22, Pin 15) → back to menu (inside a mode)
  A     (GPIO5,  Pin 29) → move selection down (same as DOWN)
  B     (GPIO6,  Pin 31) → confirm / select item

Each button wired between its GPIO pin and GND (internal pull-up used).
"""
import logging, sys, signal, time
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
PIN_UP   = 17
PIN_DOWN = 27
PIN_LEFT = 22   # back (inside a mode)
PIN_A    = 5    # acts as DOWN
PIN_B    = 6    # select / confirm

DEBOUNCE_MS = 200

ALL_PINS = (PIN_UP, PIN_DOWN, PIN_LEFT, PIN_A, PIN_B)

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

menu.render(driver)
log.info("Menu ready — UP/DOWN/A navigate, B select, LEFT back")

# ── Polling loop ──────────────────────────────────────────────────────────────
prev   = {pin: GPIO.HIGH for pin in ALL_PINS}
last_t = {pin: 0.0       for pin in ALL_PINS}

try:
    while True:
        now = time.monotonic()
        for pin in ALL_PINS:
            state = GPIO.input(pin)
            if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                if now - last_t[pin] >= DEBOUNCE_MS / 1000:
                    last_t[pin] = now
                    if pin == PIN_UP:
                        menu.up()
                        menu.render(driver)
                        log.info("UP   → %s", menu.select()[0])
                    elif pin in (PIN_DOWN, PIN_A):
                        menu.down()
                        menu.render(driver)
                        log.info("DOWN → %s", menu.select()[0])
                    elif pin == PIN_B:
                        label, _ = menu.select()
                        log.info("SELECT → %s", label)
                        _modes[label].run(driver)   # state preserved across calls
                        menu.render(driver)
                        log.info("Returned to menu")
            prev[pin] = state
        time.sleep(0.02)
finally:
    GPIO.cleanup()
    driver.close()
