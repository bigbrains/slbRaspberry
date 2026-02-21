# SLB Raspberry Pi Display Project

## Hardware
- Raspberry Pi Zero 2W
- 1.54" TFT SPI display, ST7789 driver, 240×240 px
- DC → GPIO24 (Pin 18), RST → GPIO25 (Pin 22), BLK → 3.3V (always on)
- SPI0: SCK → GPIO11, MOSI → GPIO10, CE0 → GPIO8

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

## Key files
- `display/menu.py` — `ST7789Driver` (raw SPI) + `Menu` class
- `menu_show.py`    — auto-scroll demo; also the systemd entry point
- `menu_demo.py`    — keyboard-driven demo with 20 placeholder items
- `hello_fast.py`   — minimal low-level SPI test (no PIL, bitmap font)
- `menu_show.service` — systemd unit file (installed at /etc/systemd/system/)

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
