"""
questions_demo.py — run with: sudo python3 questions_demo.py
Auto-pages through all Q&A screens, then loops.
Hold B to exit.
"""
import logging, sys, signal, time
import RPi.GPIO as GPIO

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

from display.menu import ST7789Driver
from display.simple_questions import SimpleQuestions

PIN_B        = 27
LONG_PRESS_S = 0.7

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(PIN_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)

driver = ST7789Driver()
sq     = SimpleQuestions()

log.info("chars/line=%d  avail_lines=%d  pages=%d",
         sq._chars_per_line, sq._avail_lines, len(sq._pages))

def _shutdown(sig, frame):
    GPIO.cleanup()
    driver.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)

sq.render(driver)
log.info("Rendered page 1/%d  — hold B to exit", len(sq._pages))

b_was_down = False
b_down_at  = 0.0
last_page_t = time.monotonic()

try:
    while True:
        now    = time.monotonic()
        b_down = GPIO.input(PIN_B) == GPIO.LOW

        if b_down and not b_was_down:
            b_down_at = now
        elif not b_down and b_was_down:
            if now - b_down_at >= LONG_PRESS_S:
                log.info("B long press — exiting")
                break
        b_was_down = b_down

        if now - last_page_t >= 4.0:
            last_page_t = now
            if not sq.next_page():
                sq.page = 0
            sq.render(driver)
            log.info("Rendered page %d/%d", sq.page + 1, len(sq._pages))

        time.sleep(0.02)
finally:
    GPIO.cleanup()
    driver.close()
