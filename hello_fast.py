import spidev
import RPi.GPIO as GPIO
import time

DC = 24
RST = 25

W, H = 240, 240

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(DC, GPIO.OUT)
GPIO.setup(RST, GPIO.OUT)

spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 4000000  # сначала 4MHz (стабильнее). Потом можно 8-16MHz
spi.mode = 0

def cmd(c):
    GPIO.output(DC, 0)
    spi.writebytes([c])

def data_bytes(b: bytes):
    GPIO.output(DC, 1)
    # spidev любит <=4096 байт за вызов
    for i in range(0, len(b), 1024):
        spi.writebytes(list(b[i:i+1024]))

def reset():
    GPIO.output(RST, 0)
    time.sleep(0.05)
    GPIO.output(RST, 1)
    time.sleep(0.12)

def init():
    reset()
    cmd(0x01); time.sleep(0.15)   # SWRESET
    cmd(0x11); time.sleep(0.15)   # SLPOUT
    cmd(0x3A); data_bytes(bytes([0x55]))  # 16-bit color
    cmd(0x36); data_bytes(bytes([0x00]))  # MADCTL
    cmd(0x21)                     # INVON (часто надо)
    cmd(0x29); time.sleep(0.1)    # DISPON

def set_window(x0, y0, x1, y1):
    cmd(0x2A)
    data_bytes(bytes([x0>>8, x0&0xFF, x1>>8, x1&0xFF]))
    cmd(0x2B)
    data_bytes(bytes([y0>>8, y0&0xFF, y1>>8, y1&0xFF]))
    cmd(0x2C)

def fill565(color):
    set_window(0, 0, W-1, H-1)
    hi = (color >> 8) & 0xFF
    lo = color & 0xFF
    chunk = bytes([hi, lo]) * 512  # 1024 байта
    total = W * H
    GPIO.output(DC, 1)
    while total > 0:
        n = 512 if total >= 512 else total
        spi.writebytes(list(chunk[:n*2]))
        total -= n

# 5x7 шрифт (только нужные буквы)
font = {
'H':[0x7F,0x08,0x08,0x08,0x7F],
'E':[0x7F,0x49,0x49,0x49,0x41],
'L':[0x7F,0x40,0x40,0x40,0x40],
'O':[0x3E,0x41,0x41,0x41,0x3E],
'W':[0x7F,0x02,0x0C,0x02,0x7F],
'R':[0x7F,0x09,0x19,0x29,0x46],
'D':[0x7F,0x41,0x41,0x22,0x1C],
' ':[0x00,0x00,0x00,0x00,0x00],
}

def draw_text_window(x, y, text, fg=0xFFFF, bg=0x0000):
    # окно только под текст: ширина = len*6-1, высота=7
    tw = len(text)*6 - 1
    th = 7
    set_window(x, y, x+tw-1, y+th-1)

    # подготовим буфер RGB565
    fg_hi, fg_lo = (fg>>8)&0xFF, fg&0xFF
    bg_hi, bg_lo = (bg>>8)&0xFF, bg&0xFF

    buf = bytearray(tw * th * 2)
    for i, ch in enumerate(text):
        cols = font.get(ch, font[' '])
        for col in range(5):
            line = cols[col]
            for row in range(7):
                px = i*6 + col
                py = row
                idx = (py*tw + px)*2
                if line & (1 << row):
                    buf[idx] = fg_hi; buf[idx+1] = fg_lo
                else:
                    buf[idx] = bg_hi; buf[idx+1] = bg_lo
        # 1 колонка пробела между буквами уже по умолчанию bg (шестая)
    data_bytes(buf)

try:
    init()
    fill565(0x0000)  # чёрный фон
    draw_text_window(40, 110, "HELLO WORLD", fg=0xFFFF, bg=0x0000)
    print("Hello World should be visible now")
finally:
    spi.close()
    GPIO.cleanup()
