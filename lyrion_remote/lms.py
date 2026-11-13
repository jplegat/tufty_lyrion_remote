# Lyrion Music Server JSON-RPC client.
#
# Requests are POSTed to /jsonrpc.js one at a time over a keep-alive socket.
# A queued request with a key replaces any queued request with the same key, so
# a burst of volume presses goes out as a single request for the final value.
#
# Nothing here touches badge globals at import time, so the protocol code also
# runs under desktop Python (see tools/desktop_test.py).

import json

ENDPOINT = "/jsonrpc.js"
HEADERS = {"Content-Type": "application/json"}

# a=artist l=album d=duration c=coverid K=artwork_url N=remote_title
STATUS_TAGS = "tags:alcdKN"

REPEAT_OFF = 0
REPEAT_ONE = 1
REPEAT_ALL = 2

# Seconds of silence before a request is abandoned
TIMEOUT = 4

# Milliseconds per frame spent driving a request forward
STEP_BUDGET_MS = 3


def request_body(player, cmd):
    return json.dumps({"id": 1, "method": "slim.request", "params": [player or "", cmd]}).encode()


def _num(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    return int(_num(value, default))


class Status:
    # The fields of an LMS "status" reply that the remote shows, with the
    # player's quirks (string numbers, negative volume when muted) ironed out.

    def __init__(self, result):
        loop = result.get("playlist_loop") or [{}]
        track = loop[0]

        self.connected = bool(_int(result.get("player_connected")))
        self.power = bool(_int(result.get("power")))
        self.mode = result.get("mode", "stop")

        volume = _int(result.get("mixer volume"))
        self.muted = volume < 0
        self.volume = abs(volume)

        self.time = _num(result.get("time"))
        self.duration = _num(track.get("duration", result.get("duration")))
        self.remote = bool(_int(result.get("remote")))

        self.shuffle = _int(result.get("playlist shuffle"))
        self.repeat = _int(result.get("playlist repeat"))
        self.sleep = _num(result.get("will_sleep_in"))

        self.tracks = _int(result.get("playlist_tracks"))
        self.index = _int(result.get("playlist_cur_index"))

        self.title = track.get("title") or result.get("current_title") or ""
        self.artist = track.get("artist") or ""
        # Internet radio has no album, the station name stands in for it
        self.album = track.get("album") or track.get("remote_title") or ""

        self.art_key = "{}|{}".format(track.get("coverid", ""), track.get("artwork_url", ""))

    @property
    def live(self):
        return self.remote and self.duration <= 0

    @property
    def playing(self):
        return self.mode == "play"


def parse_players(result):
    players = []
    for p in result.get("players_loop", []):
        players.append({
            "id": p["playerid"],
            "name": p.get("name") or p["playerid"],
            "connected": bool(_int(p.get("connected"))),
            "power": bool(_int(p.get("power"))),
            "playing": bool(_int(p.get("isplaying"))),
        })
    return players


def parse_favorites(result):
    items = []
    for item in result.get("loop_loop", []):
        items.append({
            "id": item["id"],
            "name": item.get("name") or "?",
            "audio": bool(_int(item.get("isaudio"))),
            "folder": bool(_int(item.get("hasitems"))),
        })
    return items


def artwork_path(player, size):
    # "_o" keeps the aspect ratio rather than padding to a square
    return "/music/current/cover_{0}x{0}_o.jpg?player={1}".format(size, player)


class Channel:
    # One HTTP request at a time to the server, driven a step per frame by
    # poll(). The badge's AsyncFetch never blocks the render loop.

    def __init__(self, host, port, max_bytes):
        from asyncfetch import AsyncFetch

        self._done = AsyncFetch.DONE
        self._error = AsyncFetch.ERROR
        self._idle = AsyncFetch.IDLE

        self._fetch = AsyncFetch(host, port, use_tls=False, timeout=TIMEOUT, max_bytes=max_bytes)

        # Report HTTP errors through the status rather than raising mid-step
        self._fetch.on_error(lambda fetch: True)

        self.busy = False

    def start(self, path, body=None):
        method = "GET" if body is None else "POST"
        self._fetch.fetch(path, data=body, method=method, headers=HEADERS)
        self.busy = True

    def poll(self):
        # The response body once the request completes, None while it is still in
        # flight. Raises OSError if it fails.
        import time

        deadline = time.ticks_add(time.ticks_ms(), STEP_BUDGET_MS)

        while True:
            try:
                status = self._fetch.update()
            except Exception:
                self._abandon()
                raise

            if status == self._done:
                self.busy = False
                return bytes(self._fetch.body)

            if status in (self._error, self._idle):
                self._abandon()
                raise OSError("HTTP {}".format(self._fetch.http_status))

            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return None

    def _abandon(self):
        self.busy = False
        self._fetch.reset()


class Client:
    # Queues JSON-RPC requests on one channel, and artwork downloads on another
    # so a slow image never holds up a button press. Callbacks get the reply's
    # "result" dict (or the image bytes), or None if the request failed.

    def __init__(self, rpc, art):
        self._rpc = rpc
        self._art = art

        self._queue = []  # [key, body, callback]
        self._rpc_callback = None

        self._art_next = None  # (path, callback), only the newest one matters
        self._art_callback = None

        self.error = None  # the last failure, cleared by the next success
        self.ok_at = None  # when the server last answered

    def request(self, player, cmd, callback=None, key=None):
        body = request_body(player, cmd)

        if key is not None:
            for item in self._queue:
                if item[0] == key:
                    item[1] = body
                    item[2] = callback
                    return

        self._queue.append([key, body, callback])

    def artwork(self, path, callback):
        self._art_next = (path, callback)

    @property
    def idle(self):
        return not self._queue and not self._rpc.busy

    def update(self, now):
        self._pump_rpc(now)
        self._pump_art()

    def _pump_rpc(self, now):
        if not self._rpc.busy:
            if not self._queue:
                return
            _, body, self._rpc_callback = self._queue.pop(0)
            self._rpc.start(ENDPOINT, body)

        try:
            body = self._rpc.poll()
            if body is None:
                return
            result = json.loads(body).get("result") or {}

        except (OSError, ValueError) as e:
            self._fail(e)
            return

        self.error = None
        self.ok_at = now
        callback, self._rpc_callback = self._rpc_callback, None
        if callback:
            callback(result)

    def _fail(self, error):
        # The server is likely down, so drop the backlog rather than replaying a
        # stale string of commands when it comes back
        self.error = error
        callbacks = [self._rpc_callback] + [item[2] for item in self._queue]
        self._rpc_callback = None
        self._queue = []
        for callback in callbacks:
            if callback:
                callback(None)

    def _pump_art(self):
        if not self._art.busy:
            if self._art_next is None:
                return
            path, self._art_callback = self._art_next
            self._art_next = None
            self._art.start(path)

        try:
            body = self._art.poll()
        except OSError:
            body = None
        else:
            if body is None:
                return

        callback, self._art_callback = self._art_callback, None
        callback(body)
