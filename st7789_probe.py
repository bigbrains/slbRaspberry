import spidev
import RPi.GPIO as GPIO
import time

DC = 24
RST = 25

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(DC, GPIO.OUT)
GPIO.setup(RST, GPIO.OUT)

spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 1000000  # 1MHz для стабильности на dupont
spi.mode = 0

def cmd(c):
    GPIO.output(DC, 0)
    spi.writebytes([c])

def data_bytes(b: bytes):
    GPIO.output(DC, 1)
    for i in range(0, len(b), 1024):  # <=4096 безопасно, берём 1024
        spi.writebytes(list(b[i:i+1024]))

def reset():
    GPIO.output(RST, 0); time.sleep(0.05)
    GPIO.output(RST, 1); time.sleep(0.12)

def init(madctl, invert_on):
    reset()
    cmd(0x01); time.sleep(0.15)          # SWRESET
    cmd(0x11); time.sleep(0.15)          # SLPOUT
    cmd(0x3A); data_bytes(bytes([0x55])) # 16-bit
    cmd(0x36); data_bytes(bytes([madctl]))
    if invert_on:
        cmd(0x21)                        # INVON
    else:
        cmd(0x20)                        # INVOFF
    cmd(0x29); time.sleep(0.10)          # DISPON

def set_window(x0, y0, x1, y1):
    cmd(0x2A)
    data_bytes(bytes([x0>>8, x0&0xFF, x1>>8, x1&0xFF]))
    cmd(0x2B)
    data_bytes(bytes([y0>>8, y0&0xFF, y1>>8, y1&0xFF]))
    cmd(0x2C)

def fill_rect(x, y, w, h, color565):
    set_window(x, y, x+w-1, y+h-1)
    hi = (color565 >> 8) & 0xFF
    lo = color565 & 0xFF
    chunk = bytes([hi, lo]) * 512  # 1024 bytes
    total = w * h
    GPIO.output(DC, 1)
    while total > 0:
        n = 512 if total >= 512 else total
        spi.writebytes(list(chunk[:n*2]))
        total -= n

try:
    # частые варианты MADCTL для rotation/flip
    madctls = [0x00, 0x60, 0xC0, 0xA0]   # 0, MX/MV, MY, MX+MY(+MV)
    inversions = [True, False]

    # частые смещения для 240x240 на 240x320
    offsets = [
        (0, 0),
        (0, 80),
        (0, 40),
        (52, 40),
        (0, 20),
    ]

    # пробуем как 240x240, так и "окно" внутри 240x320
    sizes = [
        (240, 240),
        (240, 320),
    ]

    step = 1
    for inv in inversions:
        for mad in madctls:
            init(mad, inv)
            for (ox, oy) in offsets:
                for (w, h) in sizes:
                    print(f"STEP {step}: inv={inv} mad=0x{mad:02X} off=({ox},{oy}) size={w}x{h}")
                    # рисуем красным/зелёным/синим
                    fill_rect(ox, oy, min(240, w), min(240, h), 0xF800)  # RED
                    time.sleep(0.7)
                    fill_rect(ox, oy, min(240, w), min(240, h), 0x07E0)  # GREEN
                    time.sleep(0.7)
                    fill_rect(ox, oy, min(240, w), min(240, h), 0x001F)  # BLUE
                    time.sleep(0.7)
                    step += 1

finally:
    spi.close()
    GPIO.cleanup()
