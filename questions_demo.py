"""
questions_demo.py — run with: sudo python3 questions_demo.py
Auto-pages through all Q&A screens, then loops.
"""
import logging, sys, signal, time

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

from display.menu import ST7789Driver
from display.simple_questions import SimpleQuestions

driver = ST7789Driver()
sq     = SimpleQuestions()

log.info("chars/line=%d  avail_lines=%d  pages=%d",
         sq._chars_per_line, sq._avail_lines, len(sq._pages))

def _shutdown(sig, frame):
    driver.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)

sq.render(driver)
log.info("Rendered page 1/%d", len(sq._pages))

try:
    while True:
        time.sleep(4)
        if not sq.next_page():
            sq.page = 0
        sq.render(driver)
        log.info("Rendered page %d/%d", sq.page + 1, len(sq._pages))
finally:
    driver.close()
