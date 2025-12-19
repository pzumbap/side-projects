#!/usr/bin/env python3
import time
from gpiozero import DigitalInputDevice

GPIO_PIN = 17           # pick your GPIO (BCM numbering)
DEBOUNCE_S = 0.2
COOLDOWN_S = 60         # don't spam: 1 alert per minute

last_sent = 0

# active_state=False means "LOW = active" (collector pulling down)
alarm_in = DigitalInputDevice(GPIO_PIN, pull_up=True, bounce_time=DEBOUNCE_S, active_state=False)

def on_alarm():
    global last_sent
    now = time.time()
    if now - last_sent < COOLDOWN_S:
        return
    last_sent = now
    print("ALARM TRIGGERED!")
    # call your notification function(s) here
    # send_sms(...)
    # send_whatsapp(...)
    # make_call(...)

alarm_in.when_activated = on_alarm

print("Watching for alarm trigger on GPIO", GPIO_PIN)
while True:
    time.sleep(1)
