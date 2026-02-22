"""
buttons_demo.py — run with: sudo python3 buttons_demo.py
Shows which button is currently pressed on the ST7789 display.

Wiring (each button between GPIO pin and GND, internal pull-up enabled):
  D-pad Up    → GPIO17  Pin 11
  D-pad Down  → GPIO27  Pin 13
  D-pad Left  → GPIO22  Pin 15
  D-pad Right → GPIO23  Pin 16
  Button A    → GPIO5   Pin 29
  Button B    → GPIO6   Pin 31
  GND         → Pin 14 (D-pad) or Pin 30/34 (A/B)
"""
import logging, sys, signal, time
import RPi.GPIO as GPIO
from PIL import Image, ImageDraw
from display.menu import ST7789Driver, _load_font

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Button map: label → GPIO pin ─────────────────────────────────────────────
BUTTONS = {
    "UP":    17,
    "DOWN":  27,
    "LEFT":  22,
    "RIGHT": 23,
    "A":      5,
    "B":      6,
}

# ── Display constants ─────────────────────────────────────────────────────────
W, H      = 240, 240
C_BG      = (10,  10,  10)
C_HDR_BG  = (25,  80, 160)
C_HDR_FG  = (255, 255, 255)
C_NONE    = (80,  80,  80)
C_PRESSED = (80, 220,  80)
C_ARROW   = (100, 200, 255)
C_BTN     = (255, 180,  50)

# ── Setup ─────────────────────────────────────────────────────────────────────
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for pin in BUTTONS.values():
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

driver   = ST7789Driver()
font_hdr = _load_font(13)
font_big = _load_font(36)
font_sm  = _load_font(11)

def _shutdown(sig, frame):
    GPIO.cleanup()
    driver.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)


def render(pressed: set[str]):
    img = Image.new("RGB", (W, H), C_BG)
    d   = ImageDraw.Draw(img)

    # Header
    d.rectangle((0, 0, W - 1, 23), fill=C_HDR_BG)
    d.text((6, 5), "Button Test", font=font_hdr, fill=C_HDR_FG)

    # Big label of pressed button(s)
    label = " + ".join(pressed) if pressed else "—"
    color = C_PRESSED if pressed else C_NONE
    try:
        bw = font_big.getlength(label)
    except AttributeError:
        bw = font_big.getbbox(label)[2]
    d.text(((W - bw) // 2, 70), label, font=font_big, fill=color)

    # D-pad visualisation (centre of screen, lower half)
    cx, cy = W // 2, 165
    r = 22   # button circle radius
    positions = {
        "UP":    (cx,      cy - 48),
        "DOWN":  (cx,      cy + 48),
        "LEFT":  (cx - 48, cy),
        "RIGHT": (cx + 48, cy),
    }
    labels_pos = {
        "UP": "▲", "DOWN": "▼", "LEFT": "◀", "RIGHT": "▶",
    }
    for name, (bx, by) in positions.items():
        fill = C_PRESSED if name in pressed else (40, 40, 40)
        d.ellipse((bx - r, by - r, bx + r, by + r), fill=fill, outline=C_ARROW, width=2)
        lbl = labels_pos[name]
        try:
            lw = font_sm.getlength(lbl)
        except AttributeError:
            lw = font_sm.getbbox(lbl)[2]
        d.text((bx - lw // 2, by - 7), lbl, font=font_sm, fill=C_HDR_FG)

    # A / B buttons (right side)
    for name, (bx, by) in [("A", (cx + 90, cy - 16)), ("B", (cx + 90, cy + 16))]:
        fill = C_BTN if name in pressed else (40, 40, 40)
        d.ellipse((bx - r, by - r, bx + r, by + r), fill=fill, outline=C_BTN, width=2)
        try:
            lw = font_sm.getlength(name)
        except AttributeError:
            lw = font_sm.getbbox(name)[2]
        d.text((bx - lw // 2, by - 7), name, font=font_sm, fill=C_BG if name in pressed else C_HDR_FG)

    driver.blit(img)


log.info("Button test running. Press Ctrl-C to stop.")
last_pressed: set[str] = set()
render(last_pressed)

try:
    while True:
        pressed = {name for name, pin in BUTTONS.items() if GPIO.input(pin) == GPIO.LOW}
        if pressed != last_pressed:
            log.info("Pressed: %s", pressed or "none")
            render(pressed)
            last_pressed = pressed
        time.sleep(0.02)   # 50 Hz polling
finally:
    GPIO.cleanup()
    driver.close()
