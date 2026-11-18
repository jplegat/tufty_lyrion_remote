# Lyrion Remote for Tufty 2350

A badge app that controls a [Lyrion Music Server](https://lyrion.org) player:
now playing with artwork, transport, volume, player choice, favorites, the
TuneIn radio directory and the music library.

## Setup

Put the badge in disk mode (double-tap RESET) and add the server to
`secrets.py` next to the WiFi details:

```python
LMS_HOST = "192.168.1.150"
LMS_PORT = 9000
```

Then copy the app over and eject:

```sh
./deploy.sh          # badge already in disk mode
./deploy.sh --disk   # or let the script switch it over USB (needs mpremote)
```

It shows up in the badge menu as **Lyrion Remote**, as the first icon, so it's
already selected when the badge starts. The stock menu sorts apps by folder
name, so `deploy.sh` also installs `badge_menu/app.py`, a copy of the v3.1.1
menu that puts the apps in its `PINNED` list first. It only replaces the stock
v3.1.1 menu or an earlier copy of its own, and otherwise leaves the menu alone
and says so. A firmware update restores the stock menu; deploy again after one.

## Controls

| Screen      | Button  | Tap                        | Hold                          |
|-------------|---------|----------------------------|-------------------------------|
| Now Playing | B       | play / pause               | open the menu                 |
|             | A       | previous track* / station† | skip back 10 s                |
|             | C       | next track / station†      | skip forward 10 s             |
|             | UP/DOWN | volume +/- 5               | keep changing                 |
| Lists       | UP/DOWN | move                       | scroll, faster the longer held |
|             | B       | open / play                | play all, or add to queue     |
|             | C       | next letter (A-Z) or page  | keep jumping                  |
|             | A       | back                       | back to Now Playing           |

\* more than 5 s into a track, A restarts it instead.
† while a single radio stream plays, A and C flip through your favorite stations.
HOME returns to the badge menu.

The menu (hold B) has:

- **Player**: pick which player to control (remembered across launches)
- **Favorites**: your LMS favorites, including folders
- **Radio**: the TuneIn directory (local, music, sports, news, talk, by
  location or language, podcasts); search needs a keyboard so it's left out
- **Library**: Artists, Albums, Genres, Playlists, New Music and Random Mix.
  Tapping a track plays its album from that track; holding B on an artist,
  album, genre or playlist plays all of it
- Shuffle, repeat, a sleep timer and player power

Long lists page in in the background (all 1245 artists of the test library
in about 3.5 s); a pulsing dot next to the position shows it's still loading.

After 2 minutes without a button press the screen dims and polling slows down;
the first press only wakes it. After 10 minutes on battery the badge sleeps.

## Layout

- `lyrion_remote/__init__.py`: entry point, buttons, screens, power handling
- `lyrion_remote/remote.py`: player state, polling and optimistic updates
- `lyrion_remote/browse.py`: favorites, radio and library lists, paged in
- `lyrion_remote/lms.py`: JSON-RPC protocol and the request queue
- `lyrion_remote/ui.py`: drawing (HIRES, 320x240)
- `lyrion_remote/asyncfetch.py`: non-blocking HTTP, vendored from the badge firmware
- `badge_menu/app.py`: the badge's launcher, vendored from the firmware, with this app pinned first

## Development tools

```sh
python3 tools/desktop_test.py          # protocol and state tests against the real server
mpremote run tools/device_check.py     # WiFi + server + artwork check on the badge
mpremote run tools/device_shot.py      # screenshot every screen to /shot_*.png on the badge
python3 tools/make_icon.py             # regenerate icon.png
```
