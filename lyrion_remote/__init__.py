# Lyrion Remote: control a Lyrion Music Server player from the badge.
#
# Now Playing:  B play/pause (hold for the menu)
#               A previous, C next (hold to skip back/forward)
#               UP/DOWN volume (hold to repeat)
# Lists:        UP/DOWN move, B select, A back
#
# Needs LMS_HOST (and optionally LMS_PORT) in secrets.py next to the WiFi details.

import os
import sys

# Work from wherever the app was launched, /system/apps or an mpremote mount
try:
    APP_DIR = __file__.rsplit("/", 1)[0]
except NameError:
    APP_DIR = "/system/apps/lyrion_remote"
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

import secrets
import wifi
from badgeware import State

import lms
import ui
from remote import Remote, SEEK_STEP_S, VOLUME_STEP

secrets.require("LMS_HOST")
HOST = secrets.LMS_HOST
PORT = int(getattr(secrets, "LMS_PORT", 9000))

badge.mode(HIRES)
screen.antialias = image.X2

LONG_MS = 450
REPEAT_MS = {BUTTON_UP: 150, BUTTON_DOWN: 150, BUTTON_A: 350, BUTTON_C: 350}

DIM_AFTER_MS = 2 * 60 * 1000
SLEEP_AFTER_MS = 10 * 60 * 1000  # on battery only
DIM_LEVEL = 0.15

state = {"player": None}
State.load("lyrion_remote", state)


class Buttons:
    # Turns raw button state into taps (released before LONG_MS), one "long"
    # event once held that long, and "repeat" events every REPEAT_MS after that.

    ALL = (BUTTON_A, BUTTON_B, BUTTON_C, BUTTON_UP, BUTTON_DOWN)

    def __init__(self):
        self._down = {}  # button -> when it went down
        self._long = set()  # buttons whose long press has fired
        self._next = {}  # button -> when its next repeat is due
        self._muted = False
        self.clear()

    def clear(self):
        self.pressed = set()
        self.taps = set()
        self.longs = set()
        self.repeats = set()

    def mute(self):
        # Swallow the current press, used when it only wakes the screen
        self._muted = True
        self.clear()

    @property
    def active(self):
        return bool(self._down)

    def update(self, now):
        self.clear()

        for b in Buttons.ALL:
            if badge.pressed(b):
                self._down[b] = now
                self._long.discard(b)
                self.pressed.add(b)

            if b not in self._down:
                continue

            if badge.released(b):
                if b not in self._long:
                    self.taps.add(b)
                del self._down[b]
                continue

            if b not in self._long and now - self._down[b] >= LONG_MS:
                self._long.add(b)
                self.longs.add(b)
                self._next[b] = now

            if b in self._long and b in REPEAT_MS and now >= self._next[b]:
                self.repeats.add(b)
                self._next[b] = now + REPEAT_MS[b]

        if self._muted:
            self._muted = self.active
            self.clear()


# -- screens --------------------------------------------------------------------

class NowPlaying:
    def update(self, b):
        if BUTTON_B in b.taps:
            remote.toggle()
        if BUTTON_B in b.longs:
            show(Menu())

        if BUTTON_A in b.taps:
            remote.previous()
        if BUTTON_C in b.taps:
            remote.next()
        if BUTTON_A in b.repeats:
            remote.seek(-SEEK_STEP_S)
        if BUTTON_C in b.repeats:
            remote.seek(SEEK_STEP_S)

        for button, step in ((BUTTON_UP, VOLUME_STEP), (BUTTON_DOWN, -VOLUME_STEP)):
            if button in b.pressed or button in b.repeats:
                remote.volume(step)

    def draw(self):
        header(remote.player_name)
        ui.now_playing(remote, art_image)


class List:
    # A scrolling list; subclasses fill self.rows and handle select()

    title = ""
    empty = "Nothing here"

    def __init__(self):
        self.rows = None
        self.index = 0
        self.top = 0
        self.loading = False

    def update(self, b):
        for button, step in ((BUTTON_UP, -1), (BUTTON_DOWN, 1)):
            if button in b.pressed or button in b.repeats:
                self.move(step)
        if BUTTON_A in b.taps:
            self.back()
        if BUTTON_B in b.taps and self.rows:
            self.select(self.index)

    def move(self, step):
        if not self.rows:
            return
        self.index = max(0, min(len(self.rows) - 1, self.index + step))
        self.top = max(min(self.top, self.index), self.index - ui.LIST_ROWS + 1)

    def back(self):
        show(Menu())

    def draw(self):
        ui.list_screen(self.title, self.rows, self.index, self.top, self.loading, self.empty)


class Menu(List):
    title = "Menu"

    def __init__(self):
        super().__init__()
        self.actions = []

    def update(self, b):
        self.build()
        super().update(b)

    def build(self):
        s = remote.status
        self.rows, self.actions = [], []

        def add(text, value, action):
            self.rows.append((text, value, None, False))
            self.actions.append(action)

        add("Player", remote.player_name, lambda: show(Players()))
        add("Favorites", "", lambda: show(Favorites()))
        if s is not None:
            add("Shuffle", "On" if s.shuffle else "Off", remote.toggle_shuffle)
            add("Repeat", ui.REPEAT_NAMES[s.repeat], remote.cycle_repeat)
            add("Sleep timer", "{} min".format(int(s.sleep // 60) + 1) if s.sleep > 0 else "Off", remote.cycle_sleep)
            add("Power", "On" if s.power else "Off", remote.toggle_power)
        self.index = min(self.index, len(self.rows) - 1)

    def select(self, i):
        self.actions[i]()

    def back(self):
        show(NowPlaying())

    def draw(self):
        if not self.rows:
            self.build()
        super().draw()


class Players(List):
    title = "Players"
    empty = "No players found"

    def __init__(self):
        super().__init__()
        self.players = remote.players or []
        self.loading = True
        self.fill()
        remote.refresh_players(self.loaded)

    def loaded(self, players):
        self.loading = False
        if players is not None:
            self.players = players
            self.fill()

    def fill(self):
        self.rows = []
        for i, p in enumerate(self.players):
            if not p["connected"]:
                dot, value = ui.FAINT, "offline"
            elif p["playing"]:
                dot, value = ui.GOOD, "playing"
            elif p["power"]:
                dot, value = ui.ACCENT, "on"
            else:
                dot, value = ui.FAINT, "off"
            self.rows.append((p["name"], value, dot, False))
            if p["id"] == remote.player_id and self.loading:
                self.index = i
        self.move(0)

    def select(self, i):
        remote.select_player(self.players[i]["id"])
        show(NowPlaying())


class Favorites(List):
    title = "Favorites"
    empty = "No favorites yet"

    def __init__(self, folder=None, parent=None):
        super().__init__()
        self.folder = folder  # (item_id, name) of the folder shown, None for the top
        self.parent = parent
        self.items = None
        if folder:
            self.title = folder[1]
        self.loading = True
        remote.load_favorites(folder[0] if folder else None, self.loaded)

    def loaded(self, items):
        self.loading = False
        self.items = items or []
        self.rows = [(item["name"], "", None, item["folder"] and not item["audio"]) for item in self.items]
        if items is None:
            self.empty = "Couldn't load favorites"

    def select(self, i):
        item = self.items[i]
        if item["audio"]:
            remote.play_favorite(item["id"])
            show(NowPlaying())
        elif item["folder"]:
            show(Favorites((item["id"], item["name"]), self))

    def back(self):
        show(self.parent or Menu())


def show(screen_):
    global current
    current = screen_


# -- status bar -----------------------------------------------------------------

_meters = {"at": None, "connected": False}


def header(title):
    # Battery and signal are slow-ish to read, so sample them every few seconds
    # (or straight away when WiFi comes or goes)
    now = badge.ticks
    connected = wifi.is_connected()
    if _meters["at"] is None or now - _meters["at"] > 5000 or connected != _meters["connected"]:
        _meters["at"] = now
        _meters["connected"] = connected
        _meters["battery"] = badge.battery_level()
        _meters["charging"] = badge.is_charging()
        try:
            _meters["rssi"] = wifi.wlan.status("rssi") if connected else None
        except (AttributeError, OSError, ValueError):
            _meters["rssi"] = None
    ui.header(title, _meters["battery"], _meters["charging"], _meters["rssi"], remote.offline)


# -- power ----------------------------------------------------------------------

last_input = badge.ticks
dimmed = False


def set_dimmed(value):
    global dimmed
    dimmed = value
    display.backlight(DIM_LEVEL if value else 1.0)


def manage_power(now):
    global last_input

    if buttons.active:
        last_input = now
        if dimmed:
            set_dimmed(False)
            buttons.mute()

    idle_for = now - last_input

    if not dimmed and idle_for > DIM_AFTER_MS:
        set_dimmed(True)

    if idle_for > SLEEP_AFTER_MS and not badge.usb_connected():
        ui.background()
        ui.message("Sleeping", "Press a button to wake the badge.")
        display.update()
        badge.sleep()


# -- main loop ------------------------------------------------------------------

def save_player(player_id):
    state["player"] = player_id
    State.save("lyrion_remote", state)


client = lms.Client(lms.Channel(HOST, PORT, 64 * 1024), lms.Channel(HOST, PORT, 32 * 1024))
remote = Remote(client, state["player"])
remote.on_player_change = save_player

buttons = Buttons()
current = NowPlaying()

art_image = None
art_version = 0


def update_art():
    global art_image, art_version
    if remote.art_version == art_version:
        return
    art_version = remote.art_version
    art_image = None
    if remote.art:
        try:
            art_image = image.load(remote.art)
        except Exception as e:  # noqa: BLE001
            print("Artwork decode failed:", e)
        remote.art = None


def update():
    now = badge.ticks
    buttons.update(now)
    manage_power(now)

    ui.background()

    if not wifi.connect():
        header("Lyrion Remote")
        ui.message("Connecting to WiFi", wifi.status()[1], busy=True)
        return None

    remote.idle = dimmed
    remote.update(now)

    if remote.players is None:
        header("Lyrion Remote")
        if remote.offline:
            ui.message("Can't reach Lyrion", "{}:{}\n{}".format(HOST, PORT, remote.client.error), ui.WARN)
        else:
            ui.message("Connecting to Lyrion", "{}:{}".format(HOST, PORT), busy=True)
        return None

    if not remote.players:
        header("Lyrion Remote")
        ui.message("No players", "The server doesn't know about any players yet.")
        return None

    update_art()
    current.update(buttons)
    current.draw()
    return None


def on_exit():
    display.backlight(1.0)


run(update)
