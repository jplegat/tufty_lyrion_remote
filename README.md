# Lyrion Remote for Tufty 2350

A badge app that controls a [Lyrion Music Server](https://lyrion.org) player:
now playing with artwork, transport, volume, player choice and favorites.

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

It shows up in the badge menu as **Lyrion Remote**.

## Controls

| Screen      | Button  | Tap              | Hold               |
|-------------|---------|------------------|--------------------|
| Now Playing | B       | play / pause     | open the menu      |
|             | A       | previous track*  | skip back 10 s     |
|             | C       | next track       | skip forward 10 s  |
|             | UP/DOWN | volume +/- 5     | keep changing      |
| Lists       | UP/DOWN | move             | keep moving        |
|             | B       | select           |                    |
|             | A       | back             |                    |

\* more than 5 s into a track, A restarts it instead. HOME returns to the badge menu.

The menu has the player picker (remembered across launches), favorites
(including folders), shuffle, repeat, a sleep timer and player power.

After 2 minutes without a button press the screen dims and polling slows down;
the first press only wakes it. After 10 minutes on battery the badge sleeps.

## Layout

- `lyrion_remote/__init__.py`: entry point, buttons, screens, power handling
- `lyrion_remote/remote.py`: player state, polling and optimistic updates
- `lyrion_remote/lms.py`: JSON-RPC protocol and the request queue
- `lyrion_remote/ui.py`: drawing (HIRES, 320x240)
- `lyrion_remote/asyncfetch.py`: non-blocking HTTP, vendored from the badge firmware

## Development tools

```sh
python3 tools/desktop_test.py          # protocol and state tests against the real server
mpremote run tools/device_check.py     # WiFi + server + artwork check on the badge
mpremote run tools/device_shot.py      # screenshot every screen to /shot_*.png on the badge
python3 tools/make_icon.py             # regenerate icon.png
```
