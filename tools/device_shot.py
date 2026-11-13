# Screenshot each of the app's screens on the badge:
#
#   mpremote run tools/device_shot.py
#   mpremote cp :/shot_now.png :/shot_menu.png ... .
#
# Stands in for the firmware's run() loop so the app can be driven from here:
# each entry renders one screen for a while, then saves the framebuffer.

import builtins
import sys
import time

import screenshot

APP = "/system/apps/lyrion_remote"

SHOTS = (
    ("now", None, 1500),
    ("menu", "Menu", 1500),
    ("players", "Players", 2500),
    ("favorites", "Favorites", 2500),
)


def frame(update):
    badge.clear()
    update()
    display.update()
    badge.poll()


def fake_run(update):
    app = sys.modules[APP]

    # Let WiFi, the first status and the artwork arrive before the first shot
    start = time.ticks_ms()
    while not (app.remote.status and app.art_image) and time.ticks_diff(time.ticks_ms(), start) < 20000:
        frame(update)
    print("ready after {} ms".format(time.ticks_diff(time.ticks_ms(), start)))

    for name, screen_class, duration in SHOTS:
        if screen_class:
            app.show(getattr(app, screen_class)())
        frames = 0
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < duration:
            frame(update)
            frames += 1
        fps = frames * 1000 / duration
        print("saved {} ({:.1f} fps)".format(screenshot.save("/shot_{}.png".format(name)), fps))
    print("SHOTS DONE")


builtins.run = fake_run
__import__(APP)
