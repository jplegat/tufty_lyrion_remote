# Screenshot the app's screens on the badge:
#
#   mpremote run tools/device_shot.py
#   mpremote cp :/shot_now.png :/shot_menu.png ... .
#
# Stands in for the firmware's run() loop so the app can be driven from here:
# each step sets up a screen through the app's own objects, renders it for a
# while, then saves the framebuffer. Nothing is played.

import builtins
import sys
import time

import screenshot

APP = "/system/apps/lyrion_remote"

# Names of the shots to save, or None for all of them (each save takes seconds)
SAVE = None


def to_screen(make):
    return lambda app: app.show(make(app))


def select_named(name):
    # Open the row with this name in the current list
    def step(app):
        rows = app.current.rows
        for i, r in enumerate(rows):
            if r["name"] == name:
                app.current.index = i
                app.current.select(i)
                return
    return step


def select_index(i):
    def step(app):
        app.current.move(i)
        app.current.select(app.current.index)
    return step


def jump(times):
    def step(app):
        for _ in range(times):
            app.current.jump()
    return step


# (name, setup, milliseconds to render before the shot)
SHOTS = (
    ("now", None, 1500),
    ("menu", to_screen(lambda app: app.Menu()), 1000),
    ("library", to_screen(lambda app: app.Browser(app.browse.LibraryFeed())), 800),
    ("artists", select_named("Artists"), 3000),
    ("artists_jump", jump(4), 250),
    ("albums", select_index(0), 2000),
    ("tracks", select_index(0), 2000),
    ("radio", to_screen(lambda app: app.Browser(app.browse.RadioFeed())), 2000),
    ("radio_music", select_named("Music"), 2500),
    ("toast", lambda app: (app.show(app.NowPlaying()), app.toast("Bobs Grunge")), 600),
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

    for name, setup, duration in SHOTS:
        # Saving a shot takes seconds, and badge.ticks only moves on poll(), so
        # catch it up first or anything timed from setup expires at once
        badge.poll()
        if setup:
            setup(app)
        frames = 0
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < duration:
            frame(update)
            frames += 1
        if SAVE is None or name in SAVE:
            fps = frames * 1000 / duration
            print("saved {} ({:.1f} fps)".format(screenshot.save("/shot_{}.png".format(name)), fps))
    print("SHOTS DONE")


builtins.run = fake_run
__import__(APP)
