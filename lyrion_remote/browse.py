# Browsable lists on the server: favorites, the radio directory and the music
# library.
#
# A Feed describes one list: the query that pages through it, how a reply turns
# into rows, and what a row does. B on a row opens a deeper Feed or plays it;
# holding B plays everything under a folder, or adds a single item to the queue.
# Actions return a Feed to open, a command to send, or None.
#
# Rows are dicts: name, value (right-hand text), key (sort letter), id, and the
# folder/audio flags. Nothing here touches badge globals, so it runs on desktop
# Python too.

from lms import clean, _int

PAGE = 100
MAX_ROWS = 5000


def row(name, id=None, value="", key="", folder=False, audio=False):
    # A row that neither opens nor plays is just text, and is drawn dimmed
    return {"name": clean(name) or "?", "id": id, "value": value, "key": key,
            "folder": folder, "audio": audio, "dim": not folder and not audio}


def duration(seconds):
    seconds = int(_int(seconds))
    return "{}:{:02d}".format(seconds // 60, seconds % 60) if seconds else ""


def letter(r):
    # The letter a row files under. Library rows carry the server's own sort key,
    # which skips articles ("The Beatles" files under B).
    key = r["key"] or r["name"][:1]
    return key[:1].upper()


class Feed:
    title = ""
    loop = "loop_loop"  # where the reply keeps its items
    scoped = False  # whether the query must name the player
    rows = None  # a fixed list, for feeds that need no query
    can_add = False  # whether a single item can be added to the queue
    alphabetical = False  # sorted by name, so it can be jumped through by letter

    def query(self, start, count):
        raise NotImplementedError

    def row(self, item):
        raise NotImplementedError

    def parse(self, result):
        # (rows, items consumed, total on the server)
        items = result.get(self.loop) or []
        rows = []
        for item in items:
            r = self.row(item)
            if r is not None:
                rows.append(r)
        return rows, len(items), _int(result.get("count"))

    def open(self, rows, i):
        return None

    def play(self, rows, i):
        return None

    def play_all(self, rows, i):
        return None

    def add(self, rows, i):
        return None


class Loader:
    # Pages a Feed's rows in from the server. pump() asks for the next page when
    # none is in flight, so a list fills in for as long as it is on screen.

    def __init__(self, remote, feed):
        self.remote = remote
        self.feed = feed
        self.rows = list(feed.rows) if feed.rows is not None else []
        self.total = len(self.rows) if feed.rows is not None else None
        self.offset = 0
        self.busy = False
        self.failed = False

    @property
    def done(self):
        return self.total is not None and (self.offset >= self.total or len(self.rows) >= MAX_ROWS)

    def pump(self):
        if self.busy or self.failed or self.feed.rows is not None or self.done:
            return

        def loaded(result):
            self.busy = False
            if result is None:
                self.failed = True
                return
            rows, consumed, total = self.feed.parse(result)
            self.rows.extend(rows)
            self.offset += consumed
            # A reply short of what the count promised means the list is done
            self.total = total if consumed else self.offset

        self.busy = True
        self.remote.query(self.feed.query(self.offset, PAGE), loaded, self.feed.scoped)


# -- favorites, radio, podcasts: the server's generic browse lists --------------

class XMLFeed(Feed):
    # Lists the server serves through its XMLBrowser: favorites, the TuneIn
    # directory, podcasts and other plugins. Every level is "<cmd> items".

    scoped = True
    can_add = True

    def __init__(self, cmd, title, item_id=None):
        self.cmd = cmd
        self.title = title
        self.item_id = item_id

    def query(self, start, count):
        q = [self.cmd, "items", start, count]
        if self.item_id:
            q.append("item_id:" + self.item_id)
        return q

    def row(self, item):
        if item.get("type") == "search":
            return None  # needs a keyboard
        return row(item.get("name") or item.get("title"), str(item.get("id")),
                   folder=bool(_int(item.get("hasitems"))), audio=bool(_int(item.get("isaudio"))))

    def _play(self, r, how):
        return [self.cmd, "playlist", how, "item_id:" + r["id"]]

    def open(self, rows, i):
        r = rows[i]
        return XMLFeed(self.cmd, r["name"], r["id"]) if r["folder"] else None

    def play(self, rows, i):
        r = rows[i]
        return self._play(r, "play") if r["audio"] and not r["folder"] else None

    def play_all(self, rows, i):
        r = rows[i]
        return self._play(r, "play") if r["audio"] and r["folder"] else None

    def add(self, rows, i):
        r = rows[i]
        return self._play(r, "add") if r["audio"] and not r["folder"] else None


class RadioFeed(Feed):
    # The radio directory's top level, each entry its own XMLBrowser command
    title = "Radio"
    loop = "radioss_loop"  # sic, the server's spelling

    def query(self, start, count):
        return ["radios", start, count]

    def row(self, item):
        if item.get("cmd") == "search":
            return None
        return row(item.get("name"), item.get("cmd"), folder=True)

    def open(self, rows, i):
        return XMLFeed(rows[i]["id"], rows[i]["name"])


# -- the music library ----------------------------------------------------------

def _load(*terms):
    return ["playlistcontrol", "cmd:load"] + list(terms)


class LibraryFeed(Feed):
    title = "Library"

    def __init__(self):
        self.rows = [row(name, id, folder=id != "random", audio=id == "random") for name, id in (
            ("Artists", "artists"), ("Albums", "albums"), ("Genres", "genres"),
            ("Playlists", "playlists"), ("New Music", "new"), ("Random Mix", "random"))]

    def open(self, rows, i):
        kind = rows[i]["id"]
        if kind == "artists":
            return ArtistsFeed()
        if kind == "albums":
            return AlbumsFeed()
        if kind == "genres":
            return GenresFeed()
        if kind == "playlists":
            return PlaylistsFeed()
        if kind == "new":
            return AlbumsFeed(new=True)
        return None

    def play(self, rows, i):
        return ["randomplay", "tracks"] if rows[i]["id"] == "random" else None


class ArtistsFeed(Feed):
    title = "Artists"
    loop = "artists_loop"
    alphabetical = True

    def __init__(self, genre=None):
        self.genre = genre  # (id, name) when listing one genre's artists
        if genre:
            self.title = genre[1]

    def query(self, start, count):
        q = ["artists", start, count, "tags:s"]
        if self.genre:
            q.append("genre_id:{}".format(self.genre[0]))
        return q

    def row(self, item):
        return row(item.get("artist"), item.get("id"), key=item.get("textkey") or "", folder=True, audio=True)

    def open(self, rows, i):
        return AlbumsFeed(artist=(rows[i]["id"], rows[i]["name"]), genre=self.genre)

    def play_all(self, rows, i):
        terms = ["artist_id:{}".format(rows[i]["id"])]
        if self.genre:
            terms.append("genre_id:{}".format(self.genre[0]))
        return _load(*terms)


class AlbumsFeed(Feed):
    title = "Albums"
    loop = "albums_loop"

    def __init__(self, artist=None, genre=None, new=False):
        self.artist = artist  # (id, name)
        self.genre = genre
        self.new = new
        self.alphabetical = not new
        if artist:
            self.title = artist[1]
        elif new:
            self.title = "New Music"

    def query(self, start, count):
        q = ["albums", start, count, "tags:las", "sort:new" if self.new else "sort:album"]
        if self.artist:
            q.append("artist_id:{}".format(self.artist[0]))
        if self.genre:
            q.append("genre_id:{}".format(self.genre[0]))
        return q

    def row(self, item):
        # Newest-first isn't alphabetical, so no letter key to jump by
        return row(item.get("album"), item.get("id"), "" if self.artist else clean(item.get("artist")),
                   "" if self.new else item.get("textkey") or "", folder=True, audio=True)

    def open(self, rows, i):
        return TracksFeed((rows[i]["id"], rows[i]["name"]))

    def play_all(self, rows, i):
        return _load("album_id:{}".format(rows[i]["id"]))


class TracksFeed(Feed):
    loop = "titles_loop"
    can_add = True

    def __init__(self, album):
        self.album = album
        self.title = album[1]

    def query(self, start, count):
        return ["titles", start, count, "album_id:{}".format(self.album[0]), "tags:dt", "sort:tracknum"]

    def row(self, item):
        number = item.get("tracknum")
        name = "{}. {}".format(number, clean(item.get("title"))) if number else item.get("title")
        return row(name, item.get("id"), duration(item.get("duration")), audio=True)

    def play(self, rows, i):
        # The whole album in the order shown, starting at this track
        ids = ",".join(str(r["id"]) for r in rows)
        return _load("track_id:" + ids, "play_index:{}".format(i))

    def add(self, rows, i):
        return ["playlistcontrol", "cmd:add", "track_id:{}".format(rows[i]["id"])]


class GenresFeed(Feed):
    title = "Genres"
    loop = "genres_loop"
    alphabetical = True

    def query(self, start, count):
        return ["genres", start, count, "tags:s"]

    def row(self, item):
        return row(item.get("genre"), item.get("id"), key=item.get("textkey") or "", folder=True, audio=True)

    def open(self, rows, i):
        return ArtistsFeed((rows[i]["id"], rows[i]["name"]))

    def play_all(self, rows, i):
        return _load("genre_id:{}".format(rows[i]["id"]))


class PlaylistsFeed(Feed):
    title = "Playlists"
    loop = "playlists_loop"
    alphabetical = True

    def query(self, start, count):
        return ["playlists", start, count, "tags:s"]

    def row(self, item):
        return row(item.get("playlist"), item.get("id"), key=item.get("textkey") or "", folder=True, audio=True)

    def open(self, rows, i):
        return PlaylistTracksFeed((rows[i]["id"], rows[i]["name"]))

    def play_all(self, rows, i):
        return _load("playlist_id:{}".format(rows[i]["id"]))


class PlaylistTracksFeed(Feed):
    loop = "playlisttracks_loop"
    can_add = True

    def __init__(self, playlist):
        self.playlist = playlist
        self.title = playlist[1]

    def query(self, start, count):
        return ["playlists", "tracks", start, count, "playlist_id:{}".format(self.playlist[0]), "tags:ad"]

    def row(self, item):
        return row(item.get("title"), item.get("id"), clean(item.get("artist")), audio=True)

    def play(self, rows, i):
        return _load("playlist_id:{}".format(self.playlist[0]), "play_index:{}".format(i))

    def add(self, rows, i):
        return ["playlistcontrol", "cmd:add", "track_id:{}".format(rows[i]["id"])]
