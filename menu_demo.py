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
import sys
import time

import RPi.GPIO as GPIO
from PIL import Image, ImageDraw

from display.menu import _load_font, Menu
from display.simple_questions import SimpleQuestions
from display.ai_camera import AICamera as _AICamera, CameraError
from display.wifi_menu import NetworkMode, IPInfoMode
from display.qa_result import QAResultView

log = logging.getLogger(__name__)

# ── API ───────────────────────────────────────────────────────────────────────
_API_BASE = "http://clb.modera.dev/clb"

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
_PIN_DOWN = 6
_PIN_LEFT = 22   # back to menu
_PIN_A    = 26   # GPIO26, Pin 37
_PIN_B    = 19   # GPIO19, Pin 35

_DEBOUNCE   = 0.2
_LONG_PRESS = 0.7
_ALL_PINS    = (_PIN_UP, _PIN_DOWN, _PIN_LEFT, _PIN_A, _PIN_B)


def _wait_release(pin):
    while GPIO.input(pin) == GPIO.LOW:
        time.sleep(0.01)
    time.sleep(0.05)


def _poll(prev: dict, last_t: dict, b_down_at: list) -> str | None:
    """
    Poll A and B buttons. Returns 'down', 'b_short', 'b_long', or None.
    B long press fires on release after _LONG_PRESS seconds.
    """
    now = time.monotonic()
    for pin in (_PIN_A, _PIN_B):
        state = GPIO.input(pin)
        if pin == _PIN_B:
            if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                b_down_at[0] = now
            elif prev[pin] == GPIO.LOW and state == GPIO.HIGH:
                held = now - b_down_at[0]
                prev[pin] = state
                return 'b_long' if held >= _LONG_PRESS else 'b_short'
        elif pin == _PIN_A:
            if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                if now - last_t[pin] >= _DEBOUNCE:
                    last_t[pin] = now
                    prev[pin] = state
                    return 'down'
        prev[pin] = state
    return None


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

        prev      = {p: GPIO.HIGH for p in _ALL_PINS}
        last_t    = {p: 0.0       for p in _ALL_PINS}
        b_down_at = [0.0]

        while True:
            event = _poll(prev, last_t, b_down_at)
            if event == 'b_long':
                self._save()
                return
            elif event == 'up':
                self._sq.prev_page()
                self._sq.render(driver)
            elif event in ('down', 'b_short'):
                if not self._sq.next_page():
                    self._sq.page = 0
                self._sq.render(driver)
            time.sleep(0.02)

    def _save(self):
        state = _load_state()
        state[self._STATE_KEY] = self._sq.page
        _save_state(state)
        log.info("Questions state saved: page %d", self._sq.page)


# ── AI Camera mode ────────────────────────────────────────────────────────────

class AICameraMode:
    """
    Scenario selection → camera capture → POST /api/solve → show response.

    Scenario menu:
      UP / DOWN / A — navigate
      B             — select scenario
      LEFT          — back to main menu

    Camera ready:
      B             — capture photo and submit to API
      LEFT          — back to scenario menu
    """

    _SK_SCENARIO = "ai_camera_scenario"

    def __init__(self):
        self._cam = _AICamera()

    def run(self, driver):
        _wait_release(_PIN_B)

        state    = _load_state()
        scenario = state.get(self._SK_SCENARIO)
        if scenario:
            log.info("Resuming saved scenario: %s (id=%s)",
                     self._label(scenario), scenario.get("id"))

        while True:
            if scenario is None:
                scenario = self._run_scenario_menu(driver)
                if scenario is None:
                    return   # LEFT on scenario menu → back to main menu
                s = _load_state()
                s[self._SK_SCENARIO] = scenario
                _save_state(s)

            stay = self._run_camera(driver, scenario)
            if not stay:
                s = _load_state()
                s.pop(self._SK_SCENARIO, None)
                _save_state(s)
                scenario = None

    # ── Scenario menu ──────────────────────────────────────────────────────────

    def _run_scenario_menu(self, driver) -> dict | None:
        """Returns selected scenario dict, or None if user goes back."""
        while True:
            self._cam._show_message(driver, "Loading scenarios…")
            try:
                scenarios = self._cam.fetch_scenarios(_API_BASE)
                break   # success → proceed to scenario menu
            except CameraError as e:
                log.error("fetch_scenarios: %s", e)
                action = self._run_no_network(driver)
                if action == "retry":
                    continue
                elif action == "restart":
                    log.info("Restarting app on user request")
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                else:
                    return None  # back to main menu

        if not scenarios:
            self._cam.show_error_screen(driver, "No scenarios found", duration=3)
            return None

        items = {self._label(s): s for s in scenarios}
        menu  = Menu(items, title="SCENARIO")
        menu.render(driver)
        log.info("Scenario menu: %d items", len(scenarios))

        prev      = {p: GPIO.HIGH for p in _ALL_PINS}
        last_t    = {p: 0.0       for p in _ALL_PINS}
        b_down_at = [0.0]

        while True:
            event = _poll(prev, last_t, b_down_at)
            if event == 'b_long':
                return None
            elif event == 'up':
                menu.up(); menu.render(driver)
            elif event == 'down':
                menu.down(); menu.render(driver)
            elif event == 'b_short':
                _, scenario = menu.select()
                log.info("Selected: %s (id=%s)",
                         self._label(scenario), scenario.get("id"))
                return scenario
            time.sleep(0.02)

    # ── No-network screen ─────────────────────────────────────────────────────

    def _run_no_network(self, driver) -> str:
        """Show no-network screen. Auto-retries every 3 s; also handles buttons.
        Returns: 'retry', 'restart', or 'back'."""
        AUTO_RETRY_S = 3.0

        self._cam.show_no_network(driver)

        prev        = {p: GPIO.HIGH for p in _ALL_PINS}
        last_t      = {p: 0.0       for p in _ALL_PINS}
        b_down_at   = [0.0]
        next_retry  = time.monotonic() + AUTO_RETRY_S

        while True:
            now   = time.monotonic()
            event = _poll(prev, last_t, b_down_at)
            if event == 'down':       # A button → retry now
                return "retry"
            elif event == 'b_short':  # B short → back to main menu
                return "back"
            elif event == 'b_long':   # B hold → restart app
                return "restart"

            if now >= next_retry:
                next_retry = now + AUTO_RETRY_S
                return "retry"

            time.sleep(0.02)

    # ── Camera ready loop ─────────────────────────────────────────────────────

    def _run_camera(self, driver, scenario: dict) -> bool:
        """Camera ready loop. Returns False to go back to scenario menu."""
        name = self._label(scenario)
        self._cam.show_camera_ready(driver, name)

        prev      = {p: GPIO.HIGH for p in _ALL_PINS}
        last_t    = {p: 0.0       for p in _ALL_PINS}
        b_down_at = [0.0]

        while True:
            event = _poll(prev, last_t, b_down_at)
            if event == 'b_long':
                return False
            elif event == 'b_short':
                session_id = self._capture_and_submit(driver, scenario, name)
                if session_id is not None:
                    take_new = self._run_polling(driver, session_id)
                    if not take_new:
                        return False
                self._cam.show_camera_ready(driver, name)
            time.sleep(0.02)

    # ── Capture + submit ───────────────────────────────────────────────────────

    def _capture_and_submit(self, driver, scenario: dict, name: str) -> int | None:
        """Capture photo and POST to API. Returns sessionId on success, None on failure."""
        self._cam._show_message(driver, "Capturing…")
        try:
            _, path = self._cam.capture()
            log.info("Photo saved: %s", path)
        except CameraError as e:
            log.error("Capture: %s", e)
            self._cam.show_error_screen(driver, str(e), duration=3)
            return None

        self._cam._show_message(driver, "Submitting…")
        try:
            response = self._cam.submit_photo(_API_BASE, scenario["id"], path)
            log.info("API response: %s", response)
        except CameraError as e:
            log.error("Submit: %s", e)
            self._cam.show_error_screen(driver, str(e), duration=3)
            return None

        session_id = response.get("sessionId")
        log.info("Session started: id=%s", session_id)
        return session_id

    # ── Result polling ─────────────────────────────────────────────────────────

    def _run_polling(self, driver, session_id: int) -> bool:
        """Poll /api/data/check every second. Keep polling even after results arrive
        so new updates are shown. User can take a new photo at any time.
        A       → next page (wraps)
        B short → take new photo immediately (returns True)
        B long  → back to scenario menu (returns False)"""
        version      = 0
        dots         = 0
        last_poll    = -999.0
        qa_view: QAResultView | None = None
        result_shown = False

        self._cam.show_waiting(driver, dots)

        prev      = {p: GPIO.HIGH for p in _ALL_PINS}
        b_down_at = [0.0]
        last_a    = 0.0

        while True:
            now = time.monotonic()

            # Poll every second
            if now - last_poll >= 1.0:
                last_poll = now
                try:
                    updated, new_version, data = self._cam.poll_data_check(
                        _API_BASE, session_id, version)
                    if updated:
                        version = new_version
                        log.info("Data update v%s", version)
                        parsed = data
                        if isinstance(parsed, str):
                            try:
                                import re as _re
                                cleaned = _re.sub(r',\s*([}\]])', r'\1', parsed)
                                parsed = json.loads(cleaned)
                            except Exception:
                                pass
                        if isinstance(parsed, list):
                            qa_view = QAResultView(parsed)
                            qa_view.render(driver)
                        else:
                            qa_view = None
                            self._cam.show_data_result(driver, parsed)
                        result_shown = True
                    elif not result_shown:
                        dots += 1
                        self._cam.show_waiting(driver, dots)
                except CameraError as e:
                    log.warning("Poll error: %s", e)
                    if not result_shown:
                        dots += 1
                        self._cam.show_waiting(driver, dots)

            # Button handling
            for pin in (_PIN_A, _PIN_B):
                state = GPIO.input(pin)
                if pin == _PIN_B:
                    if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                        b_down_at[0] = now
                    elif prev[pin] == GPIO.LOW and state == GPIO.HIGH:
                        held = now - b_down_at[0]
                        prev[pin] = state
                        if held >= _LONG_PRESS:
                            return False        # back to scenario menu
                        else:
                            return True         # B short → take new photo now
                elif pin == _PIN_A:
                    if prev[pin] == GPIO.HIGH and state == GPIO.LOW:
                        if now - last_a >= _DEBOUNCE and qa_view is not None:
                            last_a = now
                            if not qa_view.next_page():
                                qa_view.page = 0   # wrap to first
                            qa_view.render(driver)
                prev[pin] = state

            time.sleep(0.05)

    @staticmethod
    def _label(s: dict) -> str:
        return s.get("name") or s.get("title") or s.get("description") or f"#{s['id']}"


# ── Button test mode ──────────────────────────────────────────────────────────

class ButtonTestMode:
    """
    Shows which buttons are currently pressed.
    B long press → back to menu.
    """

    _BUTTONS = {"UP": 17, "DOWN": 6, "LEFT": 22, "RIGHT": 23, "A": 26, "B": 19}

    C_BG      = (10,  10,  10)
    C_HDR_BG  = (25,  80, 160)
    C_HDR_FG  = (255, 255, 255)
    C_NONE    = (80,  80,  80)
    C_PRESSED = (80, 220,  80)
    C_ARROW   = (100, 200, 255)
    C_BTN     = (255, 180,  50)

    def __init__(self):
        self._font_hdr = _load_font(13)
        self._font_big = _load_font(36)
        self._font_sm  = _load_font(11)

    def run(self, driver):
        _wait_release(_PIN_B)
        last_pressed = set()
        b_down_at    = 0.0
        self._render(driver, last_pressed)

        while True:
            now     = time.monotonic()
            pressed = {name for name, pin in self._BUTTONS.items()
                       if GPIO.input(pin) == GPIO.LOW}

            b_now = "B" in pressed
            b_was = "B" in last_pressed
            if b_now and not b_was:
                b_down_at = now
            elif not b_now and b_was:
                if now - b_down_at >= _LONG_PRESS:
                    return

            if pressed != last_pressed:
                self._render(driver, pressed)
                last_pressed = pressed

            time.sleep(0.02)

    def _render(self, driver, pressed: set):
        W, H = 240, 240
        img = Image.new("RGB", (W, H), self.C_BG)
        d   = ImageDraw.Draw(img)

        d.rectangle((0, 0, W - 1, 23), fill=self.C_HDR_BG)
        d.text((6, 5), "Button Test", font=self._font_hdr, fill=self.C_HDR_FG)

        label = " + ".join(sorted(pressed)) if pressed else "—"
        color = self.C_PRESSED if pressed else self.C_NONE
        try:
            bw = self._font_big.getlength(label)
        except AttributeError:
            bw = self._font_big.getbbox(label)[2]
        d.text(((W - bw) // 2, 70), label, font=self._font_big, fill=color)

        cx, cy, r = W // 2, 165, 22
        for name, (bx, by) in [("UP",    (cx, cy-48)), ("DOWN", (cx, cy+48)),
                                ("LEFT",  (cx-48, cy)), ("RIGHT", (cx+48, cy))]:
            fill = self.C_PRESSED if name in pressed else (40, 40, 40)
            d.ellipse((bx-r, by-r, bx+r, by+r), fill=fill, outline=self.C_ARROW, width=2)
            lbl = {"UP": "▲", "DOWN": "▼", "LEFT": "◀", "RIGHT": "▶"}[name]
            try:
                lw = self._font_sm.getlength(lbl)
            except AttributeError:
                lw = self._font_sm.getbbox(lbl)[2]
            d.text((bx - lw//2, by - 7), lbl, font=self._font_sm, fill=self.C_HDR_FG)

        for name, (bx, by) in [("A", (cx+90, cy-16)), ("B", (cx+90, cy+16))]:
            fill = self.C_BTN if name in pressed else (40, 40, 40)
            d.ellipse((bx-r, by-r, bx+r, by+r), fill=fill, outline=self.C_BTN, width=2)
            try:
                lw = self._font_sm.getlength(name)
            except AttributeError:
                lw = self._font_sm.getbbox(name)[2]
            d.text((bx - lw//2, by - 7), name, font=self._font_sm,
                   fill=self.C_BG if name in pressed else self.C_HDR_FG)

        driver.blit(img)


# ── Menu items ────────────────────────────────────────────────────────────────

MENU_ITEMS: dict[str, type] = {
    "Questions":   QuestionsMode,
    "AI Camera":   AICameraMode,
    "Button Test": ButtonTestMode,
    "Network":     NetworkMode,
    "IP Info":     IPInfoMode,
}
