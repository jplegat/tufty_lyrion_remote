# Lyrion Remote: control a Lyrion Music Server player from the badge.
#
# Now Playing:  B play/pause (hold for the menu)
#               A previous, C next (hold to skip back/forward); on a radio
#               stream they flip between favorite stations instead
#               UP/DOWN volume (hold to repeat)
# Lists:        UP/DOWN move (hold to scroll, faster the longer it's held)
#               B open or play (hold to play everything / add to the queue)
#               C jump to the next letter, A back (hold for Now Playing)
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

import browse
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

# Rows moved per repeat once UP/DOWN has been held this long
SCROLL_SPEEDS = ((4000, 20), (2000, 5), (0, 1))

DIM_AFTER_MS = 2 * 60 * 1000
SLEEP_AFTER_MS = 10 * 60 * 1000  # on battery only
DIM_LEVEL = 0.15

TOAST_MS = 1800
LETTER_MS = 700

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
        self.now = 0
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

    def held_for(self, b):
        return self.now - self._down[b] if b in self._down else 0

    def update(self, now):
        self.now = now
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

        station = None
        if BUTTON_A in b.taps:
            station = remote.previous()
        if BUTTON_C in b.taps:
            station = remote.next()
        if station:
            toast(station)

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
    # A scrolling list of row dicts (name, value, plus optional dot, folder and
    # dim); subclasses fill self.rows and handle select()

    title = ""
    empty = "Nothing here"

    def __init__(self, parent=None):
        self.parent = parent
        self.rows = None
        self.index = 0
        self.top = 0
        self.loading = False

    def update(self, b):
        for button, step in ((BUTTON_UP, -1), (BUTTON_DOWN, 1)):
            if button in b.pressed:
                self.move(step)
            elif button in b.repeats:
                held = b.held_for(button)
                for after, speed in SCROLL_SPEEDS:
                    if held >= after:
                        self.move(step * speed)
                        break
        if BUTTON_A in b.taps:
            self.back()
        if BUTTON_A in b.longs:
            show(NowPlaying())
        if BUTTON_B in b.taps and self.rows:
            self.select(self.index)

    def move(self, step):
        if not self.rows:
            return
        self.index = max(0, min(len(self.rows) - 1, self.index + step))
        self.top = max(min(self.top, self.index), self.index - ui.LIST_ROWS + 1)

    def back(self):
        show(self.parent or Menu())

    def labels(self):
        return ("Back", "Select", None)

    def draw(self, position="", hint=None):
        ui.list_screen(self.title, self.rows, self.index, self.top, self.loading, self.empty,
                       position, self.labels(), hint)


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

        def add(text, value, action, folder=False):
            self.rows.append({"name": text, "value": value, "folder": folder})
            self.actions.append(action)

        add("Player", remote.player_name, lambda: show(Players(self)), True)
        add("Favorites", "", lambda: show(Browser(browse.XMLFeed("favorites", "Favorites"), self)), True)
        add("Radio", "", lambda: show(Browser(browse.RadioFeed(), self)), True)
        add("Library", "", lambda: show(Browser(browse.LibraryFeed(), self)), True)
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

    def __init__(self, parent):
        super().__init__(parent)
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
            self.rows.append({"name": p["name"], "value": value, "dot": dot})
            if p["id"] == remote.player_id and self.loading:
                self.index = i
        self.move(0)

    def select(self, i):
        remote.select_player(self.players[i]["id"])
        show(NowPlaying())


class Browser(List):
    # One level of a browse.Feed: favorites, radio or the library

    def __init__(self, feed, parent=None):
        super().__init__(parent)
        self.feed = feed
        self.title = feed.title
        self.loader = browse.Loader(remote, feed)
        self.rows = self.loader.rows
        self.letter = None
        self.letter_until = 0

    def update(self, b):
        self.loader.pump()
        self.loading = not self.loader.done and not self.loader.failed
        if self.loader.failed:
            self.empty = "Couldn't load this list"

        if (BUTTON_C in b.pressed or BUTTON_C in b.repeats) and self.rows:
            if self.feed.alphabetical:
                self.jump()
            else:
                self.page()
        if BUTTON_B in b.longs and self.rows:
            self.hold(self.index)
        super().update(b)

    def jump(self):
        # To the first row of the next letter, wrapping round at the end
        rows = self.rows
        current = browse.letter(rows[self.index])
        i = self.index + 1
        while i < len(rows) and browse.letter(rows[i]) == current:
            i += 1
        if i >= len(rows):
            i = 0 if self.loader.done else len(rows) - 1
        self.index = i
        self.top = max(0, min(i, len(rows) - ui.LIST_ROWS))
        self.letter = browse.letter(rows[i])
        self.letter_until = badge.ticks + LETTER_MS

    def page(self):
        # A screenful down, wrapping round at the end
        if self.index >= len(self.rows) - 1:
            self.index, self.top = 0, 0
        else:
            self.move(ui.LIST_ROWS)
            self.top = max(0, min(self.index, len(self.rows) - ui.LIST_ROWS))

    def select(self, i):
        r = self.rows[i]
        deeper = self.feed.open(self.rows, i)
        if deeper is not None:
            show(Browser(deeper, self))
            return
        cmd = self.feed.play(self.rows, i)
        if cmd is not None:
            remote.play(cmd)
            toast("Playing " + r["name"])
            show(NowPlaying())

    def hold(self, i):
        r = self.rows[i]
        cmd = self.feed.play_all(self.rows, i)
        if cmd is not None:
            remote.play(cmd)
            toast("Playing " + r["name"])
            show(NowPlaying())
            return
        cmd = self.feed.add(self.rows, i)
        if cmd is not None:
            remote.send(cmd)
            toast("Added " + r["name"])

    def selected(self):
        return self.rows[self.index] if self.rows else None

    def labels(self):
        r = self.selected()
        action = None
        if r is not None:
            action = "Open" if r["folder"] else "Play" if r["audio"] else None
        jump = None
        if len(self.rows) > ui.LIST_ROWS:
            jump = "A-Z" if self.feed.alphabetical else "Page"
        return ("Back", action, jump)

    def draw(self):
        r = self.selected()
        hint = None
        if r is not None and r["audio"]:
            if r["folder"]:
                hint = "hold: play all"
            elif self.feed.can_add:
                hint = "hold: add to queue"

        position = ""
        if self.rows:
            total = self.loader.total or len(self.rows)
            position = "{}/{}".format(self.index + 1, total)

        super().draw(position, hint)
        if badge.ticks < self.letter_until:
            ui.bubble(self.letter)


def show(screen_):
    global current
    current = screen_


# -- overlays -------------------------------------------------------------------

notice = {"text": "", "until": 0}


def toast(text):
    notice["text"] = text
    notice["until"] = badge.ticks + TOAST_MS


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


client = lms.Client(lms.Channel(HOST, PORT, 256 * 1024), lms.Channel(HOST, PORT, 32 * 1024))
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

    if now < notice["until"]:
        ui.toast(notice["text"])
    return None


def on_exit():
    display.backlight(1.0)


run(update)
