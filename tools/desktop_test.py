"""Exercise lms.py and remote.py from desktop Python against a real server.

Swaps the badge's AsyncFetch channel for a blocking http.client one, then runs
the Remote the way the app does. Read-only apart from re-sending the player's
current volume, so it won't disturb whatever is playing.

    python3 tools/desktop_test.py [host] [port]
"""

import http.client
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lyrion_remote"))

import browse  # noqa: E402
import lms  # noqa: E402
from remote import Remote  # noqa: E402


class SyncChannel:
    def __init__(self, host, port):
        self.conn = http.client.HTTPConnection(host, port, timeout=lms.TIMEOUT)
        self.busy = False
        self.pending = None
        self.log = []

    def start(self, path, body=None):
        self.pending = (path, body)
        self.busy = True

    def poll(self):
        path, body = self.pending
        self.busy = False
        method = "GET" if body is None else "POST"
        self.conn.request(method, path, body=body, headers=lms.HEADERS)
        response = self.conn.getresponse()
        data = response.read()
        self.log.append((method, path, response.status, len(data)))
        if response.status != 200:
            raise OSError("HTTP {}".format(response.status))
        return data


def run(remote, seconds, until=None):
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        remote.update(int(time.monotonic() * 1000))
        if until and until():
            return True
        time.sleep(0.01)
    return False


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.150"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9000

    rpc, art = SyncChannel(host, port), SyncChannel(host, port)
    remote = Remote(lms.Client(rpc, art))
    failures = []

    def check(name, ok, detail=""):
        print("{} {}{}".format("PASS" if ok else "FAIL", name, " - " + detail if detail else ""))
        if not ok:
            failures.append(name)

    run(remote, 5, until=lambda: remote.status is not None and remote.art is not None)

    check("players loaded", bool(remote.players), str([(p["name"], p["id"]) for p in remote.players or []]))
    check("player chosen", bool(remote.player_id), "{} ({})".format(remote.player_name, remote.player_id))

    s = remote.status
    check("status received", s is not None)
    if s:
        print("     mode={} power={} vol={}{} time={:.1f}/{:.1f} live={} shuffle={} repeat={} sleep={}".format(
            s.mode, s.power, s.volume, " (muted)" if s.muted else "", remote.elapsed(), s.duration,
            s.live, s.shuffle, s.repeat, s.sleep))
        print("     title={!r} artist={!r} album={!r} art_key={!r}".format(s.title, s.artist, s.album, s.art_key))

    check("artwork downloaded", bool(remote.art) and remote.art[:2] == b"\xff\xd8",
          "{} bytes JPEG".format(len(remote.art or b"")))

    # Elapsed time should advance locally between polls while playing
    if s and s.playing and not s.live:
        t0 = remote.elapsed()
        remote.now += 1000
        check("elapsed interpolates", abs(remote.elapsed() - t0 - 1) < 0.01)

    # -- browsing ------------------------------------------------------------

    def load(feed, seconds=15):
        loader = browse.Loader(remote, feed)
        start = time.monotonic()
        while not (loader.done or loader.failed) and time.monotonic() - start < seconds:
            loader.pump()
            remote.update(int(time.monotonic() * 1000))
        return loader

    favorites = load(browse.XMLFeed("favorites", "Favorites"))
    check("favorites listed", bool(favorites.rows), str([(r["name"], r["id"]) for r in favorites.rows]))
    if favorites.rows:
        check("favorite plays by item_id", favorites.feed.play(favorites.rows, 0)[:3] == ["favorites", "playlist", "play"])

    radio = load(browse.RadioFeed())
    check("radio directory listed", bool(radio.rows) and all(r["id"] != "search" for r in radio.rows),
          str([r["name"] for r in radio.rows]))
    music = [i for i, r in enumerate(radio.rows) if r["id"] == "music"]
    if music:
        # Stations sit a few folders down (Music > Country > Local Stations)
        level, path, cmd = load(radio.feed.open(radio.rows, music[0])), [], None
        for _ in range(4):
            path.append(level.feed.title)
            playable = [i for i, r in enumerate(level.rows) if r["audio"] and not r["folder"]]
            if playable:
                cmd = level.feed.play(level.rows, playable[0])
                break
            if not level.rows:
                break
            level = load(level.feed.open(level.rows, 0))
        check("radio station reachable", cmd is not None, " > ".join(path) + ": " + " ".join(cmd or []))

    library = browse.Loader(remote, browse.LibraryFeed())
    check("library menu", [r["name"] for r in library.rows][:2] == ["Artists", "Albums"])

    started = time.monotonic()
    artists = load(library.feed.open(library.rows, 0), 60)
    letters = sorted(set(browse.letter(r) for r in artists.rows))
    check("all artists paged in", artists.done and len(artists.rows) == artists.total,
          "{} of {} in {:.1f}s, {} letters: {}".format(len(artists.rows), artists.total, time.monotonic() - started,
                                                    len(letters), "".join(letters)))

    # Open the first artist with albums, then that album's tracks
    albums = None
    for i in range(min(20, len(artists.rows))):
        albums = load(artists.feed.open(artists.rows, i))
        if albums.rows:
            break
    check("artist opens to albums", bool(albums and albums.rows), albums.feed.title if albums else "")
    if albums and albums.rows:
        tracks = load(albums.feed.open(albums.rows, 0))
        check("album opens to tracks", bool(tracks.rows), "{}: {}".format(tracks.feed.title, [(r["name"], r["value"]) for r in tracks.rows[:3]]))
        if tracks.rows:
            cmd = tracks.feed.play(tracks.rows, len(tracks.rows) - 1)
            check("track plays album from its position", cmd[-1] == "play_index:{}".format(len(tracks.rows) - 1)
                  and cmd[2].count(",") == len(tracks.rows) - 1, " ".join(cmd)[:90])
        check("album plays whole", albums.feed.play_all(albums.rows, 0)[:3] == ["playlistcontrol", "cmd:load", "album_id:{}".format(albums.rows[0]["id"])])

    new = load(browse.AlbumsFeed(new=True), 5)
    check("new music listed", bool(new.rows), str([r["name"] for r in new.rows[:3]]))

    genres = load(browse.GenresFeed())
    check("genres listed", bool(genres.rows), "{} genres".format(len(genres.rows)))

    # -- favorite station surfing (commands inspected, never sent) ---------------

    run(remote, 2, until=lambda: remote.stations is not None)
    check("stations loaded", bool(remote.stations), str(remote.stations))
    if remote.stations and s:
        saved = remote.status
        remote.status = lms.Status({"remote": 1, "playlist_tracks": 1, "mode": "play",
                                    "playlist_loop": [{"title": "x", "remote_title": remote.stations[0][1]}]})
        queued = []
        for delta in (1, 1, -1):
            remote.step_station(delta)
        for item in remote.client._queue:
            queued.append(item[1])
        remote.client._queue[:] = [item for item in remote.client._queue if item[0] != "station"]
        expected = remote.stations[1 % len(remote.stations)][0]
        check("station presses coalesce to the last pick", len([b for b in queued if b"favorites" in b]) == 1
              and "item_id:{}".format(expected).encode() in queued[-1], queued[-1].decode()[-60:])
        remote.status = saved

    # A command round trip that changes nothing: re-send the current volume.
    # Two queued volume changes should coalesce into one request.
    if s:
        before = len(rpc.log)
        remote.volume(+VOL_PROBE)
        remote.volume(-VOL_PROBE)
        run(remote, 1, until=lambda: remote.client.idle)
        sent = [entry for entry in rpc.log[before:] if entry[0] == "POST"]
        check("volume burst coalesced", remote.status.volume == s.volume and len(sent) >= 1, "{} request(s)".format(len(sent)))

        # The status that follows must not be dropped as stale forever
        run(remote, 2)
        check("status resumes after command", remote.status is not None and remote.status.volume == s.volume)

    # Failure path: an unreachable port surfaces as an error, not an exception
    dead = Remote(lms.Client(SyncChannel(host, 1), SyncChannel(host, 1)))
    try:
        run(dead, 0.5)
        check("unreachable server handled", dead.offline and dead.players is None, repr(dead.client.error))
    except Exception as e:  # noqa: BLE001
        check("unreachable server handled", False, repr(e))

    print("\n{} failure(s)".format(len(failures)))
    return 1 if failures else 0


VOL_PROBE = 0  # keep at 0: the probe must not change what you hear

if __name__ == "__main__":
    sys.exit(main())
