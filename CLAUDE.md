# SLB Raspberry Pi Display Project

## Hardware
- Raspberry Pi Zero 2W
- 1.54" TFT SPI display, ST7789 driver, 240×240 px

### Display wiring
| Display pin | GPIO    | Pi pin | Notes              |
|-------------|---------|--------|--------------------|
| DC          | GPIO24  | Pin 18 |                    |
| RST         | GPIO25  | Pin 22 |                    |
| BLK         | 3.3V    | Pin 17 | backlight always on |
| SCK         | GPIO11  | Pin 23 | SPI0 clock         |
| MOSI / SDA  | GPIO10  | Pin 19 | SPI0 data          |
| CS / CE     | GPIO8   | Pin 24 | SPI0 CE0           |
| VCC         | 3.3V    | Pin 1  |                    |
| GND         | GND     | Pin 6  |                    |

### Button wiring
Each button wired between its GPIO pin and GND. Internal pull-ups are used — **no external resistors needed**.

| Button     | GPIO   | Pi pin | GND pin |
|------------|--------|--------|---------|
| D-pad UP   | GPIO17 | Pin 11 | Pin 14  |
| D-pad DOWN | GPIO27 | Pin 13 | Pin 14  |
| D-pad LEFT | GPIO22 | Pin 15 | Pin 14  |
| D-pad RIGHT| GPIO23 | Pin 16 | Pin 14  |
| Button A   | GPIO5  | Pin 29 | Pin 30  |
| Button B   | GPIO6  | Pin 31 | Pin 30  |

## Running the menu display


### Python only (quickest way to test)
```bash
ssh pi@raspberrypi.local
cd ~/slb
sudo .venv/bin/python menu_show.py   # auto-scrolling demo
sudo .venv/bin/python menu_demo.py   # keyboard-navigable demo (w/s or ↑/↓, Enter, q)
sudo .venv/bin/python hello_fast.py  # basic "HELLO WORLD" hardware test
```

### As a systemd service (runs on boot)
```bash
# Start
sudo systemctl start menu_show

# Stop
sudo systemctl stop menu_show

# Status + recent logs
sudo systemctl status menu_show

# Restart after code changes
sudo systemctl restart menu_show

# Enable/disable autostart on boot
sudo systemctl enable menu_show
sudo systemctl disable menu_show
```

### Logs
```bash
sudo tail -f /var/log/slb/menu_show.log   # file log
sudo journalctl -u menu_show -f           # systemd journal
```

## Running Simple Questions

```bash
ssh pi@raspberrypi.local
cd ~/slb
sudo systemctl stop menu_show          # stop the menu service first
sudo .venv/bin/python questions_demo.py  # auto-pages every 4 seconds
```

To go back to the menu:
```bash
sudo pkill -f questions_demo.py
sudo systemctl start menu_show
```

## Running button-navigated menu

```bash
ssh pi@raspberrypi.local
cd ~/slb
sudo systemctl stop menu_show        # stop auto-scroll service first
sudo .venv/bin/python menu_buttons.py  # navigate with UP/DOWN/A buttons, B to select
```

Button actions:
- **UP** (GPIO17) — move selection up
- **DOWN** (GPIO27) — move selection down
- **A** (GPIO5) — same as DOWN
- **B** (GPIO6) — confirm / select item

## Running button test

```bash
sudo .venv/bin/python buttons_demo.py  # shows which button is pressed on screen
```

## Key files
- `display/menu.py`             — `ST7789Driver` (raw SPI) + `Menu` class
- `display/simple_questions.py` — `SimpleQuestions` class (Q&A, auto-paged, vertically centred)
- `display/ai_camera.py`        — `AICamera` class (USB camera capture, saves to photos/)
- `menu_show.py`                — menu auto-scroll demo; systemd entry point
- `menu_buttons.py`             — button-navigated menu (GPIO UP/DOWN/A/B)
- `menu_demo.py`                — keyboard-driven menu demo (w/s/↑/↓, Enter, q)
- `buttons_demo.py`             — shows pressed button on display (test wiring)
- `questions_demo.py`           — Simple Questions auto-paging demo
- `ai_camera_demo.py`           — captures photo every 5s, saves to photos/
- `hello_fast.py`               — minimal low-level SPI test (no PIL)
- `menu_show.service`           — systemd unit (installed at /etc/systemd/system/)

## Sync local → Pi
```bash
rsync -av --exclude='.venv' --exclude='.git' --exclude='.idea' \
  /Users/oksanka/slbRaspberry/ pi@raspberrypi.local:~/slb/
```

## After syncing, reload the service
```bash
ssh pi@raspberrypi.local "sudo systemctl restart menu_show"
```

## Menu API
```python
from display.menu import ST7789Driver, Menu

items = {
    "WiFi Settings": WiFiSettings,   # key = label, value = class
    "Reboot":        Reboot,
}
driver = ST7789Driver()              # dc_pin=24, rst_pin=25, speed=4_000_000
menu   = Menu(items, title="SETTINGS")
menu.render(driver)                  # draw to screen

menu.up()                            # navigate
menu.down()
menu.render(driver)

label, cls = menu.select()           # get highlighted item
```

## Notes
- All display scripts must run as root (`sudo`) — required for GPIO and SPI
- SPI must be enabled: `sudo raspi-config` → Interface Options → SPI
- The systemd service uses `After=sysinit.target` (not multi-user.target)
  to avoid being blocked by the first-boot `userconfig.service`
