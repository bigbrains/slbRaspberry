"""
ai_camera_demo.py — button-navigated AI camera with scenario API

Flow:
  1. On start: check state file. If a scenario was previously selected, skip menu.
  2. Otherwise: fetch scenarios from GET /api/sessions, show scrollable menu.
  3. After selection: camera-ready screen.
  4. B pressed → capture photo, POST /api/solve, show response 5 s, back to camera-ready.
  5. LEFT pressed → back to scenario menu (clears saved state).

Buttons:
  UP   (GPIO17) — menu up
  DOWN (GPIO27) — menu down
  A    (GPIO5)  — menu down (same as DOWN)
  B    (GPIO6)  — select / capture & submit
  LEFT (GPIO22) — back to scenario menu

Run with: sudo .venv/bin/python ai_camera_demo.py
"""
import json
import logging
import os
import signal
import sys
import time

import RPi.GPIO as GPIO

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

from display.menu import ST7789Driver, Menu
from display.ai_camera import AICamera, CameraError

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE   = "http://clb.modera.dev/clb"
STATE_FILE = "/home/pi/slb/.camera_state.json"

# ── Buttons ───────────────────────────────────────────────────────────────────
PIN_UP   = 17
PIN_DOWN = 6
PIN_LEFT = 22
PIN_A    = 5
PIN_B    = 27
DEBOUNCE = 0.2
ALL_PINS = (PIN_UP, PIN_DOWN, PIN_LEFT, PIN_A, PIN_B)

# ── GPIO setup ────────────────────────────────────────────────────────────────
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
for pin in ALL_PINS:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

driver = ST7789Driver()
cam    = AICamera()


def _shutdown(sig, frame):
    GPIO.cleanup()
    driver.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT,  _shutdown)

# ── Persistent state ──────────────────────────────────────────────────────────

def _load_state() -> dict | None:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _save_state(scenario: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(scenario, f)


def _clear_state():
    try:
        os.remove(STATE_FILE)
    except FileNotFoundError:
        pass

# ── Button polling ────────────────────────────────────────────────────────────

_prev   = {pin: GPIO.HIGH for pin in ALL_PINS}
_last_t = {pin: 0.0       for pin in ALL_PINS}


def poll_button() -> int | None:
    """Return pin number of a freshly-debounced press, or None."""
    now = time.monotonic()
    for pin in ALL_PINS:
        state = GPIO.input(pin)
        if _prev[pin] == GPIO.HIGH and state == GPIO.LOW:
            if now - _last_t[pin] >= DEBOUNCE:
                _last_t[pin] = now
                _prev[pin]   = state
                return pin
        _prev[pin] = state
    return None

# ── Scenario menu ─────────────────────────────────────────────────────────────

def _scenario_label(s: dict) -> str:
    return s.get("name") or s.get("title") or s.get("description") or f"#{s['id']}"


def run_scenario_menu() -> dict:
    """Fetch scenarios, show menu, return selected scenario dict."""
    cam._show_message(driver, "Loading scenarios...")
    try:
        scenarios = cam.fetch_scenarios(API_BASE)
    except CameraError as e:
        log.error("fetch_scenarios: %s", e)
        cam.show_error_screen(driver, str(e), duration=3)
        raise

    if not scenarios:
        cam.show_error_screen(driver, "No scenarios found", duration=3)
        raise RuntimeError("No scenarios returned by API")

    items = {_scenario_label(s): s for s in scenarios}
    menu  = Menu(items, title="SCENARIO")
    menu.render(driver)
    log.info("Scenario menu: %d items", len(scenarios))

    while True:
        btn = poll_button()
        if btn == PIN_UP:
            menu.up()
            menu.render(driver)
        elif btn in (PIN_DOWN, PIN_A):
            menu.down()
            menu.render(driver)
        elif btn == PIN_B:
            label, scenario = menu.select()
            log.info("Selected: %s (id=%s)", label, scenario.get("id"))
            return scenario
        time.sleep(0.02)

# ── Camera mode ───────────────────────────────────────────────────────────────

def run_camera_mode(scenario: dict) -> bool:
    """
    Camera-ready loop for the given scenario.
    Returns True to stay in camera mode, False to go back to scenario menu.
    (This function only returns False — B stays in camera mode after each shot.)
    """
    name = _scenario_label(scenario)
    cam.show_camera_ready(driver, name)
    log.info("Camera ready — scenario: %s", name)

    while True:
        btn = poll_button()

        if btn == PIN_LEFT:
            log.info("Back to scenario menu")
            return False

        elif btn == PIN_B:
            # Capture
            cam._show_message(driver, "Capturing...")
            try:
                _, path = cam.capture()
                log.info("Photo saved: %s", path)
            except CameraError as e:
                log.error("Capture failed: %s", e)
                cam.show_error_screen(driver, str(e), duration=3)
                cam.show_camera_ready(driver, name)
                continue

            # Submit
            cam._show_message(driver, "Submitting...")
            try:
                response = cam.submit_photo(API_BASE, scenario["id"], path)
                log.info("API response: %s", response)
            except CameraError as e:
                log.error("Submit failed: %s", e)
                cam.show_error_screen(driver, str(e), duration=3)
                cam.show_camera_ready(driver, name)
                continue

            # Show result 5 s, then back to camera-ready
            cam.show_response(driver, response, duration=5.0)
            cam.show_camera_ready(driver, name)

        time.sleep(0.02)

# ── Main loop ─────────────────────────────────────────────────────────────────

try:
    scenario = _load_state()
    if scenario:
        log.info("Resuming saved state: %s (id=%s)", _scenario_label(scenario), scenario.get("id"))

    while True:
        if scenario is None:
            try:
                scenario = run_scenario_menu()
                _save_state(scenario)
            except Exception:
                time.sleep(1)
                continue

        stay_in_camera = run_camera_mode(scenario)
        if not stay_in_camera:
            _clear_state()
            scenario = None   # go back to scenario selection

finally:
    GPIO.cleanup()
    driver.close()
