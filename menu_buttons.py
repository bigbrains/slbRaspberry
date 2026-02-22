"""
menu_buttons.py — run with: sudo python3 menu_buttons.py
Navigate the menu using physical GPIO buttons.

  UP    (GPIO17, Pin 11) → move selection up
  DOWN  (GPIO27, Pin 13) → move selection down
  A     (GPIO5,  Pin 29) → move selection down  (same as DOWN)
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
PIN_A    = 5    # acts as DOWN
PIN_B    = 6    # select / confirm

DEBOUNCE_MS = 200   # ignore repeated presses within this window

# ── Setup ─────────────────────────────────────────────────────────────────────
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
# Clean up button pins first to clear any stale kernel interrupt state
for pin in (PIN_UP, PIN_DOWN, PIN_A, PIN_B):
    try:
        GPIO.cleanup(pin)
    except Exception:
        pass
for pin in (PIN_UP, PIN_DOWN, PIN_A, PIN_B):
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

driver = ST7789Driver()
menu   = Menu(MENU_ITEMS, title="SLB")

def _shutdown(sig, frame):
    GPIO.cleanup()
    driver.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)

menu.render(driver)
log.info("Menu ready — use UP/DOWN/A to navigate, B to select")

# ── Polling loop ──────────────────────────────────────────────────────────────
# Track previous pin states to detect falling edges (HIGH→LOW = pressed).
# Debounce by ignoring a pin for DEBOUNCE_MS after it fires.

prev   = {pin: GPIO.HIGH for pin in (PIN_UP, PIN_DOWN, PIN_A, PIN_B)}
last_t = {pin: 0.0       for pin in (PIN_UP, PIN_DOWN, PIN_A, PIN_B)}

try:
    while True:
        now = time.monotonic()
        for pin in (PIN_UP, PIN_DOWN, PIN_A, PIN_B):
            state = GPIO.input(pin)
            if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                if now - last_t[pin] >= DEBOUNCE_MS / 1000:
                    last_t[pin] = now
                    if pin == PIN_UP:
                        if menu.up():
                            menu.render(driver)
                            log.info("UP   → %s", menu.select()[0])
                    elif pin in (PIN_DOWN, PIN_A):
                        if menu.down():
                            menu.render(driver)
                            log.info("DOWN → %s", menu.select()[0])
                    elif pin == PIN_B:
                        label, cls = menu.select()
                        log.info("SELECT → %s (%s)", label, cls.__name__)
            prev[pin] = state
        time.sleep(0.02)   # 50 Hz
finally:
    GPIO.cleanup()
    driver.close()
