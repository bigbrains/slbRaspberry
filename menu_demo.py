"""
menu_demo.py — shared menu items and mode classes.
Imported by menu_buttons.py and menu_show.py.

QuestionsMode:
  UP / A  → previous page
  DOWN / B → next page
  LEFT    → save state and return to menu

AICameraMode:
  A       → take photo immediately
  B       → send all unsent photos to server (background, non-blocking)
  LEFT    → return to menu
  Progress bar shows upload status. New photos can be taken while uploading.
"""
import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error

import RPi.GPIO as GPIO
from PIL import Image, ImageDraw

from display.menu import _load_font
from display.simple_questions import SimpleQuestions
from display.ai_camera import AICamera as _AICamera, CameraError

log = logging.getLogger(__name__)

# ── Upload destination ────────────────────────────────────────────────────────
UPLOAD_URL = "https://google.com"   # TODO: change to your server URL

# ── Persistent state file ─────────────────────────────────────────────────────
STATE_FILE = "/home/pi/slb/state.json"

def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _save_state(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except OSError as e:
        log.warning("Could not save state: %s", e)

# ── Button pins ───────────────────────────────────────────────────────────────
_PIN_UP   = 17
_PIN_DOWN = 27
_PIN_LEFT = 22   # back to menu
_PIN_A    = 5
_PIN_B    = 6

_DEBOUNCE = 0.2
_ALL_PINS = (_PIN_UP, _PIN_DOWN, _PIN_LEFT, _PIN_A, _PIN_B)


def _wait_release(pin):
    while GPIO.input(pin) == GPIO.LOW:
        time.sleep(0.01)
    time.sleep(0.05)


# ── Questions mode ────────────────────────────────────────────────────────────

class QuestionsMode:
    """
    Manual Q&A paging.
    UP / A  → previous page
    DOWN / B → next page
    LEFT    → save state and return to menu
    """
    _STATE_KEY = "questions_page"

    def __init__(self):
        self._sq = SimpleQuestions()
        saved = _load_state().get(self._STATE_KEY, 0)
        self._sq.page = max(0, min(saved, len(self._sq._pages) - 1))

    def run(self, driver):
        self._sq.render(driver)
        _wait_release(_PIN_B)

        prev   = {p: GPIO.HIGH for p in _ALL_PINS}
        last_t = {p: 0.0       for p in _ALL_PINS}

        while True:
            now = time.monotonic()
            for pin in _ALL_PINS:
                state = GPIO.input(pin)
                if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                    if now - last_t[pin] >= _DEBOUNCE:
                        last_t[pin] = now
                        if pin == _PIN_LEFT:
                            self._save()
                            return
                        elif pin in (_PIN_UP, _PIN_A):
                            self._sq.prev_page()
                            self._sq.render(driver)
                        elif pin in (_PIN_DOWN, _PIN_B):
                            if not self._sq.next_page():
                                self._sq.page = 0
                            self._sq.render(driver)
                prev[pin] = state
            time.sleep(0.02)

    def _save(self):
        state = _load_state()
        state[self._STATE_KEY] = self._sq.page
        _save_state(state)
        log.info("Questions state saved: page %d", self._sq.page)


# ── AI Camera mode ────────────────────────────────────────────────────────────

class AICameraMode:
    """
    Manual camera + background upload.
    A     → take photo immediately
    B     → start uploading all unsent photos (non-blocking, can take more while uploading)
    LEFT  → return to menu

    Already-sent photos are never re-sent (tracked in state.json).
    Progress bar shown during upload; new photos taken during upload appear after
    the current upload batch finishes.
    """

    W, H     = 240, 240
    HDR_H    = 22
    FOOT_H   = 22
    C_HDR    = (25,  80, 160)
    C_FG     = (255, 255, 255)
    C_BG     = (10,  10,  10)
    C_HINT   = (100, 100, 100)
    C_PROG   = (80,  200,  80)
    C_PROG_BG= (40,  40,  40)
    C_WARN   = (220, 100,  60)
    C_INFO   = (220, 220, 100)

    _SK_SENT = "ai_camera_sent"
    _SK_LAST = "ai_camera_last_photo"

    def __init__(self):
        self._cam    = _AICamera()
        self._font   = _load_font(11)
        self._font_s = _load_font(9)

        state = _load_state()
        self._sent: set[str] = set(state.get(self._SK_SENT, []))

        # Try to restore last photo for display
        self._last_img: Image.Image | None = None
        last_path = state.get(self._SK_LAST)
        if last_path and os.path.exists(last_path):
            try:
                img = Image.open(last_path)
                img.load()
                self._last_img = self._cam._fit(img)
            except Exception:
                pass

        # Upload state — shared with upload thread, protected by lock
        self._lock      = threading.Lock()
        self._uploading = False
        self._up_total  = 0
        self._up_done   = 0
        self._up_failed = 0

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self, driver):
        _wait_release(_PIN_B)
        self._render(driver)

        prev        = {p: GPIO.HIGH for p in _ALL_PINS}
        last_t      = {p: 0.0       for p in _ALL_PINS}
        last_render = time.monotonic()

        while True:
            now = time.monotonic()

            # Re-render every 0.5 s to update progress bar
            if now - last_render >= 0.5:
                self._render(driver)
                last_render = now

            for pin in (_PIN_LEFT, _PIN_A, _PIN_B):
                state = GPIO.input(pin)
                if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                    if now - last_t[pin] >= _DEBOUNCE:
                        last_t[pin] = now
                        if pin == _PIN_LEFT:
                            return
                        elif pin == _PIN_A:
                            self._take_photo(driver)
                            last_render = now
                        elif pin == _PIN_B:
                            self._start_upload()
                prev[pin] = state

            time.sleep(0.02)

    # ── Photo capture ─────────────────────────────────────────────────────────

    def _take_photo(self, driver):
        self._show_status(driver, "Capturing…")
        try:
            fitted, path = self._cam.capture()
            self._last_img = fitted
            state = _load_state()
            state[self._SK_LAST] = path
            _save_state(state)
            log.info("Photo saved: %s", path)
        except CameraError as e:
            log.error("Capture error: %s", e)
            self._show_status(driver, f"Error: {e}", error=True)
            time.sleep(1.5)
        self._render(driver)

    # ── Upload ────────────────────────────────────────────────────────────────

    def _start_upload(self):
        with self._lock:
            if self._uploading:
                log.info("Upload already in progress")
                return
            try:
                all_files = sorted(
                    f for f in os.listdir(self._cam.photo_dir)
                    if f.endswith(".jpg")
                )
            except OSError:
                all_files = []

            to_send = [f for f in all_files if f not in self._sent]
            if not to_send:
                log.info("No new photos to send")
                return

            self._uploading = True
            self._up_total  = len(to_send)
            self._up_done   = 0
            self._up_failed = 0
            log.info("Starting upload of %d photos", len(to_send))

        threading.Thread(target=self._upload_worker, args=(to_send,),
                         daemon=True).start()

    def _upload_worker(self, filenames: list[str]):
        for filename in filenames:
            path = os.path.join(self._cam.photo_dir, filename)
            ok = self._upload_one(path)
            with self._lock:
                if ok:
                    self._sent.add(filename)
                    self._up_done += 1
                else:
                    self._up_failed += 1

        # Persist sent set
        state = _load_state()
        with self._lock:
            state[self._SK_SENT] = list(self._sent)
            done, failed = self._up_done, self._up_failed
            self._uploading = False
        _save_state(state)
        log.info("Upload finished — sent: %d  failed: %d", done, failed)

    def _upload_one(self, path: str) -> bool:
        try:
            with open(path, "rb") as f:
                data = f.read()
            req = urllib.request.Request(
                UPLOAD_URL,
                data=data,
                headers={
                    "Content-Type": "image/jpeg",
                    "X-Filename":   os.path.basename(path),
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30):
                pass
            return True
        except Exception as e:
            log.warning("Upload failed %s: %s", os.path.basename(path), e)
            return False

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self, driver):
        img = self._last_img.copy() if self._last_img else \
              Image.new("RGB", (self.W, self.H), self.C_BG)
        d = ImageDraw.Draw(img)

        # Header
        d.rectangle((0, 0, self.W - 1, self.HDR_H - 1), fill=self.C_HDR)
        d.text((6, 5), "AI Camera", font=self._font, fill=self.C_FG)

        # Footer
        fy = self.H - self.FOOT_H
        d.rectangle((0, fy, self.W - 1, self.H - 1), fill=(0, 0, 0))

        with self._lock:
            uploading = self._uploading
            done      = self._up_done
            failed    = self._up_failed
            total     = self._up_total

        if uploading:
            # Progress text
            label = f"Sending {done + failed}/{total}"
            if failed:
                label += f"  ({failed} err)"
            d.text((6, fy + 2), label, font=self._font_s, fill=self.C_INFO)
            # Progress bar
            bx, by, bw, bh = 6, fy + 13, self.W - 12, 5
            d.rectangle((bx, by, bx + bw, by + bh), fill=self.C_PROG_BG)
            filled = int(bw * (done + failed) / max(1, total))
            if filled > 0:
                d.rectangle((bx, by, bx + filled, by + bh), fill=self.C_PROG)
        else:
            if done > 0 or failed > 0:
                hint = f"Sent {done}"
                if failed:
                    hint += f"  Err {failed}"
                hint += "  ←:Back"
            else:
                hint = "A:Photo  B:Send  ←:Back"
            d.text((6, fy + 6), hint, font=self._font_s, fill=self.C_HINT)

        driver.blit(img)

    def _show_status(self, driver, text: str, error: bool = False):
        img = Image.new("RGB", (self.W, self.H), self.C_BG)
        d   = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.W - 1, self.HDR_H - 1), fill=self.C_HDR)
        d.text((6, 5), "AI Camera", font=self._font, fill=self.C_FG)
        color = self.C_WARN if error else (220, 220, 220)
        d.text((10, self.H // 2 - 8), text, font=self._font, fill=color)
        driver.blit(img)


# ── Menu items ────────────────────────────────────────────────────────────────

MENU_ITEMS: dict[str, type] = {
    "Questions": QuestionsMode,
    "AI Camera": AICameraMode,
}
