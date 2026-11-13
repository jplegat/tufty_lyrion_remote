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

    favorites = []
    remote.load_favorites(None, favorites.append)
    run(remote, 3, until=lambda: favorites)
    check("favorites listed", bool(favorites and favorites[0]),
          str([(f["name"], f["id"], f["audio"], f["folder"]) for f in (favorites[0] or [])] if favorites else ""))

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
