"""
menu_buttons.py — run with: sudo python3 menu_buttons.py
Navigate the menu using physical GPIO buttons.

  A  (GPIO26, Pin 37) → next item
  B  (GPIO27, Pin 13) → select item (long press = back)

Each button wired between its GPIO pin and GND (internal pull-up used).
"""
import logging
import os
import signal
import subprocess
import sys
import time
import traceback

# ── Crash persistence ─────────────────────────────────────────────────────────
# Any unhandled exception writes its traceback here.
# On next boot the display will show it before anything else.

CRASH_FILE = "/home/pi/slb/crash.txt"

def _save_crash(tb: str):
    try:
        with open(CRASH_FILE, "w") as f:
            f.write(tb)
    except Exception:
        pass

def _load_crash() -> str:
    try:
        with open(CRASH_FILE) as f:
            return f.read()
    except FileNotFoundError:
        return ""
    except Exception:
        return ""

def _clear_crash():
    try:
        os.remove(CRASH_FILE)
    except Exception:
        pass

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_DIR  = "/var/log/slb"
LOG_FILE = os.path.join(LOG_DIR, "menu_show.log")
try:
    os.makedirs(LOG_DIR, exist_ok=True)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        *([logging.FileHandler(LOG_FILE)] if os.path.isdir(LOG_DIR) else []),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)
log.info("=== menu_buttons.py starting === Python %s", sys.version.split()[0])

# ── Display helpers ───────────────────────────────────────────────────────────

def _load_font_safe(size: int):
    from PIL import ImageFont
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def _show_startup(driver, lines: list):
    from PIL import Image, ImageDraw
    W, H = 240, 240
    img  = Image.new("RGB", (W, H), (10, 10, 10))
    d    = ImageDraw.Draw(img)
    font_hdr = _load_font_safe(15)
    font     = _load_font_safe(13)
    d.rectangle((0, 0, W - 1, 34), fill=(25, 80, 160))
    d.text((10, 8), "SLB  — Starting up", font=font_hdr, fill=(255, 255, 255))
    y = 46
    for text, color in lines:
        d.text((10, y), text, font=font, fill=color)
        y += 22
    driver.blit(img)


def _show_crash_screen(driver, crash_text: str):
    """Show previous crash traceback on screen."""
    from PIL import Image, ImageDraw
    W, H = 240, 240
    img  = Image.new("RGB", (W, H), (10, 10, 10))
    d    = ImageDraw.Draw(img)
    font_hdr = _load_font_safe(13)
    font     = _load_font_safe(10)
    d.rectangle((0, 0, W - 1, 28), fill=(160, 30, 30))
    d.text((6, 7), "PREV CRASH — read crash.txt", font=font, fill=(255, 255, 255))
    y = 34
    for raw_line in crash_text.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        # wrap at 38 chars
        while raw_line:
            chunk = raw_line[:38]
            raw_line = raw_line[38:]
            d.text((4, y), chunk, font=font, fill=(220, 180, 100))
            y += 13
            if y > H - 14:
                d.text((4, y), "... (see crash.txt)", font=font, fill=(150, 150, 150))
                return driver.blit(img)
    driver.blit(img)


def _show_error_screen(driver, title: str, detail: str):
    from PIL import Image, ImageDraw
    W, H = 240, 240
    img  = Image.new("RGB", (W, H), (10, 10, 10))
    d    = ImageDraw.Draw(img)
    font_hdr = _load_font_safe(15)
    font     = _load_font_safe(11)
    d.rectangle((0, 0, W - 1, 34), fill=(160, 30, 30))
    d.text((10, 8), "ERROR", font=font_hdr, fill=(255, 255, 255))
    y = 46
    d.text((10, y), title, font=font, fill=(255, 100, 100))
    y += 20
    words = detail.split()
    line  = ""
    for w in words:
        if len(line) + len(w) + (1 if line else 0) <= 34:
            line = f"{line} {w}" if line else w
        else:
            if line:
                d.text((10, y), line, font=font, fill=(200, 200, 200))
                y += 16
                if y > H - 20:
                    break
            line = w
    if line and y <= H - 20:
        d.text((10, y), line, font=font, fill=(200, 200, 200))
    driver.blit(img)


# ── Bring up display as early as possible ─────────────────────────────────────

log.info("Initialising ST7789 driver")
try:
    import spidev
    import RPi.GPIO as GPIO
    from display.menu import ST7789Driver, Menu
    driver = ST7789Driver()
    log.info("Display driver ready")
except Exception as _drv_err:
    log.exception("Display init failed")
    _save_crash(traceback.format_exc())
    sys.exit(1)

# ── Show previous crash if any ────────────────────────────────────────────────

_prev_crash = _load_crash()
if _prev_crash:
    log.warning("Previous crash found — showing on screen")
    _show_crash_screen(driver, _prev_crash)
    time.sleep(15)   # keep visible so user can read it
    _clear_crash()

# ── Startup progress ──────────────────────────────────────────────────────────

startup_lines: list = []

def _step(text: str, ok: bool):
    color = (80, 200, 80) if ok else (220, 100, 60)
    startup_lines.append((text, color))
    _show_startup(driver, startup_lines)
    log.info("%s", text)

_step("System:  OK", True)

# ── GPIO setup ────────────────────────────────────────────────────────────────

PIN_A      = 26   # next item  (GPIO26, Pin 37)
PIN_B      = 19   # select     (GPIO19, Pin 35)
DEBOUNCE_S = 0.2
ALL_PINS   = (PIN_A, PIN_B)

try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in ALL_PINS:
        try:
            GPIO.cleanup(pin)
        except Exception:
            pass
    for pin in ALL_PINS:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    _step("GPIO:    OK", True)
except Exception as e:
    log.exception("GPIO setup failed")
    _step("GPIO:    FAIL", False)
    startup_lines.append((str(e)[:36], (200, 200, 200)))
    _show_startup(driver, startup_lines)
    _save_crash(traceback.format_exc())
    time.sleep(10)
    sys.exit(1)

# ── Imports ───────────────────────────────────────────────────────────────────

try:
    from menu_demo import MENU_ITEMS
    _step("Python:  OK", True)
except Exception as e:
    log.exception("Import failed")
    _step("Python:  FAIL", False)
    startup_lines.append((str(e)[:36], (200, 200, 200)))
    _show_startup(driver, startup_lines)
    _save_crash(traceback.format_exc())
    time.sleep(10)
    sys.exit(1)

# ── WiFi ──────────────────────────────────────────────────────────────────────

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

net = _get_network()
_step(f"WiFi:    {net or 'none'}", bool(net))

# ── Pre-instantiate modes ─────────────────────────────────────────────────────

startup_lines.append(("Loading modes...", (200, 200, 80)))
_show_startup(driver, startup_lines)
log.info("Pre-instantiating %d modes", len(MENU_ITEMS))

_modes = {}
for label, cls in MENU_ITEMS.items():
    try:
        _modes[label] = cls()
        log.info("  [OK] %s", label)
    except Exception as e:
        log.exception("  [FAIL] %s", label)
        startup_lines.append((f"  {label}: FAIL", (220, 100, 60)))
        _show_startup(driver, startup_lines)
        time.sleep(1.5)

startup_lines[-1] = ("Ready!", (80, 200, 80))
_show_startup(driver, startup_lines)
time.sleep(0.8)

# ── Build menu ────────────────────────────────────────────────────────────────

menu = Menu(MENU_ITEMS, title="SLB")
menu.network = net

def _shutdown(sig, frame):
    log.info("Signal %s — shutting down", sig)
    GPIO.cleanup()
    driver.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)

menu.render(driver)
log.info("Menu ready — A:next  B:select  B-long:back")

# ── Polling loop ──────────────────────────────────────────────────────────────

prev       = {pin: GPIO.HIGH for pin in ALL_PINS}
last_t     = {pin: 0.0       for pin in ALL_PINS}
last_net_t    = 0.0
last_render_t = 0.0
NET_INTERVAL     = 5.0
REFRESH_INTERVAL = 4.0
b_down_at   = time.monotonic()   # avoid false "held" reading on first release
HOLD_GUARD  = 1.0                # ignore B if held longer than this

try:
    while True:
        now = time.monotonic()

        if now - last_net_t >= NET_INTERVAL:
            last_net_t = now
            new_net = _get_network()
            if new_net != menu.network:
                menu.network = new_net
                menu.render(driver)
                last_render_t = now

        if now - last_render_t >= REFRESH_INTERVAL:
            last_render_t = now
            driver.reinit()
            menu.render(driver)

        for pin in ALL_PINS:
            state = GPIO.input(pin)
            if pin == PIN_B:
                if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                    b_down_at = now
                elif prev[pin] == GPIO.LOW and state == GPIO.HIGH:
                    held = now - b_down_at
                    if now - last_t[pin] >= DEBOUNCE_S:
                        last_t[pin] = now
                        if held < HOLD_GUARD:
                            label, _ = menu.select()
                            log.info("SELECT → %s", label)
                            try:
                                _modes[label].run(driver)
                            except Exception as e:
                                log.exception("Mode %s crashed", label)
                                _show_error_screen(driver, f"{label} crashed", str(e))
                                time.sleep(4)
                            # Wait for B to be fully released before returning to menu
                            # to avoid an accidental re-select on the way back
                            while GPIO.input(PIN_B) == GPIO.LOW:
                                time.sleep(0.01)
                            time.sleep(0.05)
                            b_down_at = time.monotonic()
                            prev[PIN_B] = GPIO.HIGH
                            menu.render(driver)
                            log.info("Returned to menu")
            elif pin == PIN_A:
                if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                    if now - last_t[pin] >= DEBOUNCE_S:
                        last_t[pin] = now
                        menu.down()
                        menu.render(driver)
                        log.info("NEXT → %s", menu.select()[0])
            prev[pin] = state

        time.sleep(0.02)

except Exception:
    tb = traceback.format_exc()
    log.exception("Fatal error in main loop")
    _save_crash(tb)
    _show_error_screen(driver, "Main loop crashed", tb)
    time.sleep(10)
    raise
finally:
    try:
        GPIO.cleanup()
    except Exception:
        pass
