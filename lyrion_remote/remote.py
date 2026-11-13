# Playback state for one LMS player, kept fresh by polling and updated
# optimistically on each command so the screen reacts before the server does.
#
# Every command bumps a generation counter. A status reply is only applied if no
# command was issued since its request was queued, otherwise it would briefly
# undo the optimistic change (the volume bar jumping back mid-press, say).
#
# Time is passed in as `now` (milliseconds), so this runs on desktop Python too.

from lms import Status, STATUS_TAGS, REPEAT_OFF, REPEAT_ONE, REPEAT_ALL, artwork_path, parse_players, clean, _int

POLL_MS = 1500  # normal refresh
POLL_FAST_MS = 400  # just after a command, while the server catches up
FAST_FOR_MS = 2500
POLL_IDLE_MS = 5000  # while the screen is dimmed
RETRY_MS = 3000  # after a failure

# Pressing "previous" this far into a track restarts it instead
RESTART_AFTER_S = 5

SEEK_STEP_S = 10
VOLUME_STEP = 5

SLEEP_CHOICES_MIN = (0, 15, 30, 60, 90)

ART_SIZE = 112

# How long the favorite stations list is trusted before it is fetched again
STATIONS_MS = 10 * 60 * 1000


class Remote:
    def __init__(self, client, player_id=None):
        self.client = client
        self.player_id = player_id

        self.players = None  # None until the first reply, then a list
        self.status = None
        self.now = 0

        self._status_at = 0  # when status.time was last true
        self._generation = 0
        self._status_pending = False
        self._poll_due = 0
        self._fast_until = 0
        self._failed = False

        self.idle = False  # set by the app while the screen is dimmed

        self.art = None  # JPEG bytes, waiting for the app to decode them
        self.art_version = 0  # bumped whenever the artwork changes
        self._art_key = None

        # Favorite radio stations as (position in favorites, name), for flipping
        # between them with previous/next while a stream plays
        self.stations = None
        self._stations_at = None
        self._station = None  # the last station picked from here

        self.on_player_change = None

    # -- polling --------------------------------------------------------------

    def update(self, now):
        self.now = now

        if self.players is None and self.client.idle and now >= self._poll_due:
            self.refresh_players()

        if self.player_id and not self._status_pending and now >= self._poll_due:
            self._request_status()

        if self.players and (self._stations_at is None or now - self._stations_at > STATIONS_MS):
            self._load_stations()

        self.client.update(now)

    def query(self, cmd, callback, scoped=False):
        # A read-only request, for browsing
        self.client.request(self.player_id if scoped else "", cmd, callback)

    def refresh_players(self, callback=None):
        def done(result):
            if result is None:
                self._poll_due = self.now + RETRY_MS
            else:
                self._set_players(parse_players(result))
            if callback:
                callback(self.players)

        self.client.request("", ["players", 0, 50], done, key="players")

    def _set_players(self, players):
        self.players = players
        ids = [p["id"] for p in players]
        if self.player_id in ids:
            return

        # The saved player is gone (or this is the first run): prefer one that is
        # playing, then any connected one
        choice = None
        for test in (lambda p: p["playing"], lambda p: p["connected"], lambda p: True):
            for p in players:
                if test(p):
                    choice = p["id"]
                    break
            if choice:
                break
        self.select_player(choice)

    def select_player(self, player_id):
        self.player_id = player_id
        self.status = None
        self.art = None
        self._art_key = None
        self.art_version += 1
        self._poll_due = self.now
        if self.on_player_change:
            self.on_player_change(player_id)

    @property
    def player_name(self):
        for p in self.players or ():
            if p["id"] == self.player_id:
                return p["name"]
        return ""

    def _request_status(self):
        generation = self._generation
        player = self.player_id
        self._status_pending = True

        def done(result):
            self._status_pending = False

            # The user switched players while this was in flight
            if player != self.player_id:
                return

            self._failed = result is None
            self._poll_due = self.now + self._interval()

            if result is not None and generation == self._generation:
                self._apply_status(Status(result))

        self.client.request(player, ["status", "-", 1, STATUS_TAGS], done, key="status")

    def _interval(self):
        if self._failed:
            return RETRY_MS
        if self.idle:
            return POLL_IDLE_MS
        if self.now < self._fast_until:
            return POLL_FAST_MS
        return POLL_MS

    def _apply_status(self, status):
        self.status = status
        self._status_at = self.now

        if status.art_key != self._art_key:
            self._art_key = status.art_key
            self._request_art(status.art_key)

    def _request_art(self, key):
        def done(body):
            # A newer track may have started while this downloaded
            if key == self._art_key and body:
                self.art = body
                self.art_version += 1

        self.client.artwork(artwork_path(self.player_id, ART_SIZE), done)

    @property
    def offline(self):
        # The server stopped answering (as opposed to never having answered)
        return self.client.error is not None

    # -- derived state --------------------------------------------------------

    def elapsed(self):
        s = self.status
        if s is None:
            return 0
        t = s.time
        if s.playing:
            t += (self.now - self._status_at) / 1000
        if s.duration > 0:
            t = min(t, s.duration)
        return t

    # -- commands -------------------------------------------------------------

    def _command(self, cmd, key=None):
        if not self.player_id:
            return
        self._generation += 1
        self._fast_until = self.now + FAST_FOR_MS

        def done(result):
            # Ask straight away, the reply will reflect this command
            self._poll_due = min(self._poll_due, self.now + 150)

        self.client.request(self.player_id, cmd, done, key=key)

    def _freeze_time(self, t):
        self.status.time = t
        self._status_at = self.now

    def toggle(self):
        s = self.status
        if s is None:
            return
        if s.playing:
            self._freeze_time(self.elapsed())
            s.mode = "pause"
            self._command(["pause", "1"])
        else:
            self._freeze_time(s.time)
            # "pause 0" resumes, but a stopped player needs "play"
            self._command(["play"] if s.mode == "stop" else ["pause", "0"])
            s.mode = "play"
            s.power = True

    # next() and previous() return a station name when they switch stations

    def next(self):
        if self.surfing:
            return self.step_station(1)
        self._command(["playlist", "index", "+1"])
        return None

    def previous(self):
        s = self.status
        if self.surfing:
            return self.step_station(-1)
        if s is not None and not s.live and self.elapsed() > RESTART_AFTER_S:
            self._freeze_time(0)
            self._command(["time", "0"], key="seek")
        else:
            self._command(["playlist", "index", "-1"])
        return None

    def seek(self, delta):
        s = self.status
        if s is None or s.live or s.duration <= 0:
            return
        t = max(0, min(s.duration - 1, self.elapsed() + delta))
        self._freeze_time(t)
        self._command(["time", str(int(t))], key="seek")

    def volume(self, delta):
        s = self.status
        if s is None:
            return
        s.volume = max(0, min(100, s.volume + delta))
        s.muted = False
        self._command(["mixer", "volume", str(s.volume)], key="volume")

    def toggle_shuffle(self):
        s = self.status
        if s is None:
            return
        s.shuffle = 0 if s.shuffle else 1
        self._command(["playlist", "shuffle", str(s.shuffle)], key="shuffle")

    def cycle_repeat(self):
        s = self.status
        if s is None:
            return
        s.repeat = {REPEAT_OFF: REPEAT_ALL, REPEAT_ALL: REPEAT_ONE}.get(s.repeat, REPEAT_OFF)
        self._command(["playlist", "repeat", str(s.repeat)], key="repeat")

    def toggle_power(self):
        s = self.status
        if s is None:
            return
        s.power = not s.power
        if not s.power:
            s.mode = "pause" if s.playing else s.mode
        self._command(["power", "1" if s.power else "0"], key="power")

    def cycle_sleep(self):
        # Step to the next choice above the time left, wrapping back to off
        s = self.status
        if s is None:
            return
        left_min = s.sleep / 60
        minutes = 0
        for choice in SLEEP_CHOICES_MIN:
            if choice > left_min + 1:
                minutes = choice
                break
        s.sleep = minutes * 60
        self._command(["sleep", str(minutes * 60)], key="sleep")

    def play(self, cmd, key=None):
        # Start something new (a station, an album...); playing powers the player on
        if self.status is not None:
            self.status.power = True
        self._command(cmd, key)

    def send(self, cmd):
        # Any other command for the player, adding to the queue say
        self._command(cmd)

    # -- favorite stations ----------------------------------------------------

    def _load_stations(self):
        self._stations_at = self.now

        def done(result):
            if result is None:
                return
            self.stations = []
            for i, item in enumerate(result.get("loop_loop") or []):
                if _int(item.get("isaudio")) and not _int(item.get("hasitems")):
                    self.stations.append((i, clean(item.get("name"))))

        self.client.request("", ["favorites", "items", 0, 100], done, key="stations")

    @property
    def surfing(self):
        # Previous/next flip between favorite stations while a lone stream plays
        s = self.status
        return bool(s is not None and s.live and s.tracks <= 1 and self.stations)

    def step_station(self, delta):
        # Play the favorite station delta places from the current one and return
        # its name. Fast presses send only the last pick.
        stations = self.stations
        playing = self.status.album.lower()
        pos = self._station
        for i, (_, name) in enumerate(stations):
            if name.lower() == playing:
                pos = i
                break

        if pos is None:
            pos = 0 if delta > 0 else len(stations) - 1
        else:
            pos = (pos + delta) % len(stations)
        self._station = pos
        index, name = stations[pos]

        # Show the station until the server reports what it is playing
        s = self.status
        s.title, s.artist, s.album = name, "", ""
        s.time = 0
        self._status_at = self.now
        self.art = None
        self._art_key = None
        self.art_version += 1

        # Favorites are addressed by position, which stays valid across sessions
        self.play(["favorites", "playlist", "play", "item_id:{}".format(index)], key="station")
        return name
