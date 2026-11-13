# Network check that runs on the badge, through the app's own client:
#
#   mpremote run tools/device_check.py
#
# Connects WiFi, loads players and status from LMS, downloads and decodes the
# artwork, and reports timings. Read-only: sends no playback commands.

import gc
import sys
import time

sys.path.insert(0, "/system/apps/lyrion_remote")

import secrets
import wifi


def ms_since(t):
    return time.ticks_diff(time.ticks_ms(), t)


print("firmware:", sys.version)
try:
    import fetch
    print("built-in fetch.AsyncFetch:", hasattr(fetch, "AsyncFetch"))
except ImportError:
    print("built-in fetch: missing")

t0 = time.ticks_ms()
while not wifi.connect():
    badge.poll()  # wifi's retry timer runs on badge.ticks
    if ms_since(t0) > 30000:
        raise SystemExit("WiFi timed out: " + wifi.status()[1])
    time.sleep_ms(20)
print("wifi up in {} ms, ip {}, rssi {}".format(ms_since(t0), wifi.ipv4(), wifi.wlan.status("rssi")))

import lms
from remote import Remote

client = lms.Client(lms.Channel(secrets.LMS_HOST, secrets.LMS_PORT, 64 * 1024),
                    lms.Channel(secrets.LMS_HOST, secrets.LMS_PORT, 32 * 1024))
remote = Remote(client)

marks = {}
slowest = 0
t0 = time.ticks_ms()
while ms_since(t0) < 8000:
    badge.poll()
    step = time.ticks_ms()
    remote.update(time.ticks_ms())
    slowest = max(slowest, ms_since(step))
    for name, ready in (("players", remote.players is not None), ("status", remote.status is not None),
                        ("artwork", remote.art is not None)):
        if ready and name not in marks:
            marks[name] = ms_since(t0)
    time.sleep_ms(10)

print("first reply ms:", marks)
print("slowest update() step: {} ms".format(slowest))
print("error:", client.error)

s = remote.status
if s:
    print("player: {} | {} vol {} | {!r} / {!r} / {!r}".format(remote.player_name, s.mode, s.volume, s.title, s.artist, s.album))

if remote.art:
    t = time.ticks_ms()
    img = image.load(remote.art)
    print("artwork: {} bytes -> {}x{} decoded in {} ms".format(len(remote.art), img.width, img.height, ms_since(t)))

gc.collect()
print("free heap:", gc.mem_free())
print("DEVICE CHECK DONE")
