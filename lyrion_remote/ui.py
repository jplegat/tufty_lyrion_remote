# Drawing for the remote: Now Playing, the menu lists and full-screen messages.
# Everything is laid out for HIRES (320x240).

import math

W, H = 320, 240

BG = color.rgb(14, 16, 22)
PANEL = color.rgb(30, 34, 44)
TEXT = color.rgb(240, 242, 245)
DIM = color.rgb(150, 158, 172)
FAINT = color.rgb(64, 72, 86)
ACCENT = color.rgb(246, 135, 4)  # the BadgeOS phosphor orange
GOOD = color.rgb(90, 200, 120)
WARN = color.rgb(255, 110, 90)

sans = font.load("/system/assets/fonts/MonaSans-Medium.af")

ART_X, ART_Y, ART_SIZE = 12, 34, 112
TEXT_X = ART_X + ART_SIZE + 12
TEXT_W = W - TEXT_X - 12

LIST_TOP = 34
LIST_ROW = 29
LIST_ROWS = 6

# Footer icon centres, lined up with the A, B and C buttons under the screen
FOOT_Y = 222
BUTTON_X = (53, 160, 267)

REPEAT_NAMES = ("Off", "One", "All")


# -- text -----------------------------------------------------------------------

# Measuring vector text is slow next to drawing it, and the same few strings are
# drawn every frame, so widths and fitted strings are cached
_widths = {}
_fitted = {}


def _width(text, size):
    key = (text, size)
    w = _widths.get(key)
    if w is None:
        if len(_widths) > 400:
            _widths.clear()
        screen.font = sans
        w = screen.measure_text(text, size)[0]
        _widths[key] = w
    return w


def fit(text, size, max_w):
    # Shorten text with a trailing "..." until it fits in max_w pixels
    key = (text, size, max_w)
    result = _fitted.get(key)
    if result is not None:
        return result

    if _width(text, size) <= max_w:
        result = text
    else:
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _width(text[:mid].rstrip() + "...", size) <= max_w:
                lo = mid
            else:
                hi = mid - 1
        result = text[:lo].rstrip() + "..."

    if len(_fitted) > 100:
        _fitted.clear()
    _fitted[key] = result
    return result


def wrap(text, size, max_w, max_lines):
    # Greedy word wrap, the last line shortened to fit
    key = (text, size, max_w, max_lines)
    result = _fitted.get(key)
    if result is not None:
        return result

    lines = []
    words = text.split(" ")
    while words and len(lines) < max_lines - 1:
        line = words.pop(0)
        while words and _width(line + " " + words[0], size) <= max_w:
            line += " " + words.pop(0)
        if _width(line, size) > max_w:
            # One long word: let the last line deal with it
            words.insert(0, line)
            break
        lines.append(line)
    if words:
        lines.append(fit(" ".join(words), size, max_w))

    _fitted[key] = lines
    return lines


def label(text, x, y, size, pen=TEXT, w=None, align=LEFT):
    w = w or W - x
    screen.font = sans
    screen.pen = pen
    # The box is a little wider than the fitted text so rounding never wraps it
    screen.text(fit(text, size, w), rect(x, y, w + 2, size * 2), font_size=size, align=(align, TOP))


def clock(seconds):
    seconds = int(seconds)
    h, m, s = seconds // 3600, (seconds // 60) % 60, seconds % 60
    if h:
        return "{}:{:02d}:{:02d}".format(h, m, s)
    return "{}:{:02d}".format(m, s)


# -- icons ----------------------------------------------------------------------

def _poly(points):
    screen.shape(shape.custom([vec2(x, y) for x, y in points]))


def icon_play(cx, cy, s):
    _poly([(cx - s * 0.4, cy - s / 2), (cx + s * 0.5, cy), (cx - s * 0.4, cy + s / 2)])


def icon_pause(cx, cy, s):
    bar = s * 0.32
    screen.rectangle(int(cx - s * 0.4), int(cy - s / 2), int(bar), int(s))
    screen.rectangle(int(cx + s * 0.08), int(cy - s / 2), int(bar), int(s))


def icon_next(cx, cy, s):
    _poly([(cx - s / 2, cy - s / 2), (cx + s * 0.25, cy), (cx - s / 2, cy + s / 2)])
    screen.rectangle(int(cx + s * 0.28), int(cy - s / 2), int(s * 0.2), int(s))


def icon_prev(cx, cy, s):
    _poly([(cx + s / 2, cy - s / 2), (cx - s * 0.25, cy), (cx + s / 2, cy + s / 2)])
    screen.rectangle(int(cx - s * 0.48), int(cy - s / 2), int(s * 0.2), int(s))


def icon_speaker(x, y, s):
    screen.rectangle(int(x), int(y + s * 0.3), int(s * 0.3), int(s * 0.4))
    _poly([(x + s * 0.3, y + s * 0.3), (x + s * 0.65, y), (x + s * 0.65, y + s), (x + s * 0.3, y + s * 0.7)])


def icon_note(cx, cy, s):
    screen.shape(shape.circle(cx - s * 0.15, cy + s * 0.3, s * 0.2))
    screen.rectangle(int(cx), int(cy - s * 0.45), int(s * 0.08), int(s * 0.75))
    _poly([(cx, cy - s * 0.45), (cx + s * 0.35, cy - s * 0.3), (cx + s * 0.35, cy - s * 0.15), (cx, cy - s * 0.3)])


def battery(x, y, level, charging):
    if charging:
        level = (badge.ticks / 20) % 100
    screen.pen = DIM
    screen.rectangle(x, y, 20, 10)
    screen.rectangle(x + 20, y + 3, 2, 4)
    screen.pen = BG
    screen.rectangle(x + 1, y + 1, 18, 8)
    screen.pen = WARN if level < 15 and not charging else DIM
    screen.rectangle(x + 2, y + 2, int(16 * level / 100), 6)


def signal(x, y, rssi):
    # Four bars; rssi of None means no reading
    bars = 0 if rssi is None else 4 if rssi > -55 else 3 if rssi > -65 else 2 if rssi > -75 else 1
    for i in range(4):
        h = 3 + i * 2
        screen.pen = DIM if i < bars else FAINT
        screen.rectangle(x + i * 4, y + 10 - h, 3, h)


# -- shared pieces --------------------------------------------------------------

def background():
    screen.pen = BG
    screen.clear()


def header(title, battery_level, charging, rssi, offline=False):
    right = W - 12 - 22
    battery(right, 8, battery_level, charging)
    signal(right - 24, 8, rssi)
    if offline:
        label("offline", right - 90, 5, 12, WARN, 60, RIGHT)
    label(title, 12, 5, 13, DIM, right - 110)


def bar(x, y, w, h, fraction, pen=ACCENT):
    screen.pen = FAINT
    screen.shape(shape.rounded_rectangle(x, y, w, h, h / 2))
    fraction = max(0, min(1, fraction))
    if fraction > 0:
        screen.pen = pen
        screen.shape(shape.rounded_rectangle(x, y, max(h, w * fraction), h, h / 2))


def pill(text, x, y, size, pen, text_pen=BG):
    w = _width(text, size) + 10
    screen.pen = pen
    screen.shape(shape.rounded_rectangle(x, y, w, size + 6, (size + 6) / 2))
    label(text, x + 5, y + 2, size, text_pen, w)
    return w


def footer(hints):
    # hints: three (icon_fn or text, ...) entries for A, B and C
    screen.pen = PANEL
    screen.rectangle(0, FOOT_Y - 12, W, H - FOOT_Y + 12)
    for x, hint in zip(BUTTON_X, hints):
        if hint is None:
            continue
        if callable(hint):
            screen.pen = TEXT
            hint(x, FOOT_Y, 14)
        else:
            label(hint, x - 50, FOOT_Y - 8, 13, TEXT, 100, CENTER)


def art(img):
    screen.pen = PANEL
    screen.shape(shape.rounded_rectangle(ART_X, ART_Y, ART_SIZE, ART_SIZE, 6))

    if img is None:
        screen.pen = FAINT
        icon_note(ART_X + ART_SIZE / 2, ART_Y + ART_SIZE / 2, 48)
        return

    # Scale to fit, keeping the aspect ratio
    scale = min(ART_SIZE / img.width, ART_SIZE / img.height)
    w, h = img.width * scale, img.height * scale
    screen.blit(img, rect(ART_X + (ART_SIZE - w) / 2, ART_Y + (ART_SIZE - h) / 2, w, h))


# -- screens --------------------------------------------------------------------

def now_playing(remote, art_img):
    s = remote.status
    art(art_img)

    if s is None:
        label("Loading" + _dots(), TEXT_X, ART_Y + 2, 18, DIM, TEXT_W)
        return

    if not s.connected:
        label("Player offline", TEXT_X, ART_Y + 2, 18, WARN, TEXT_W)
        label("Check that it is switched on and on the network.", TEXT_X, ART_Y + 30, 12, DIM, TEXT_W)
        return

    # Title (up to two lines), artist and album flow down from the top of the art
    y = ART_Y + 2
    for line in wrap(s.title or "Nothing playing", 19, TEXT_W, 2):
        label(line, TEXT_X, y, 19, TEXT if s.title else DIM, TEXT_W)
        y += 24
    y += 4
    if s.artist:
        label(s.artist, TEXT_X, y, 15, ACCENT, TEXT_W)
        y += 22
    if s.album:
        label(s.album, TEXT_X, y, 13, DIM, TEXT_W)
        y += 22

    # Mode tags under the text
    x, y = TEXT_X, y + 2
    tags = []
    if not s.power:
        tags.append(("OFF", WARN))
    if s.shuffle:
        tags.append(("SHUFFLE", FAINT))
    if s.repeat:
        tags.append(("REPEAT " + REPEAT_NAMES[s.repeat].upper(), FAINT))
    if s.sleep > 0:
        tags.append(("SLEEP " + str(int(s.sleep // 60) + 1) + "m", FAINT))
    for text, pen in tags:
        x += pill(text, x, y, 10, pen, TEXT) + 4

    # Progress
    y = 160
    elapsed = remote.elapsed()
    label(clock(elapsed), 12, y - 2, 12, DIM, 44)
    if s.live:
        bar(62, y + 4, 196, 4, 0)
        pill("LIVE", W - 12 - 38, y - 3, 11, ACCENT)
    else:
        bar(62, y + 4, 196, 4, elapsed / s.duration if s.duration else 0)
        label(clock(s.duration), W - 12 - 50, y - 2, 12, DIM, 50, RIGHT)

    # Volume
    y = 184
    screen.pen = DIM
    icon_speaker(12, y, 14)
    bar(36, y + 5, 222, 5, s.volume / 100, FAINT if s.muted else TEXT)
    label("MUTE" if s.muted else str(s.volume), W - 12 - 50, y, 12, DIM, 50, RIGHT)

    footer((icon_prev, icon_pause if s.playing else icon_play, icon_next))
    label("hold for menu", 160 - 40, FOOT_Y + 8, 9, DIM, 80, CENTER)


def list_screen(title, rows, index, top, loading=False, empty="Nothing here", position="",
                labels=("Back", "Select", None), hint=None):
    # rows: dicts with name and value, and optionally dot (a pen), folder and dim
    position_w = _width(position, 12) + 4 if position else 0
    label(title, 12, 5, 15, TEXT, W - 40 - position_w)
    if position:
        label(position, W - 12 - position_w, 8, 12, DIM, position_w, RIGHT)
    if loading and rows:
        # A pulsing dot while the rest of the list pages in
        screen.pen = color.rgb(246, 135, 4, 90 + int(80 * math.sin(badge.ticks / 150)))
        screen.shape(shape.circle(W - 20 - position_w, 14, 3))

    if not rows:
        label("Loading" + _dots() if loading or rows is None else empty, 12, LIST_TOP + 8, 15, DIM)
    else:
        for i in range(top, min(len(rows), top + LIST_ROWS)):
            r = rows[i]
            y = LIST_TOP + (i - top) * LIST_ROW

            if i == index:
                screen.pen = PANEL
                screen.shape(shape.rounded_rectangle(6, y, W - 12, LIST_ROW - 3, 5))
                screen.pen = ACCENT
                screen.shape(shape.rounded_rectangle(6, y + 5, 3, LIST_ROW - 13, 1))

            x = 16
            dot = r.get("dot")
            if dot is not None:
                screen.pen = dot
                screen.shape(shape.circle(x + 4, y + LIST_ROW / 2 - 1, 4))
                x += 14

            # Right-hand side: a ">" for folders, then the value to its left
            right = W - 16
            if r.get("folder"):
                label(">", right - 8, y + 4, 14, DIM, 10)
                right -= 16
            value = r.get("value")
            if value:
                value_w = min(110, _width(value, 14) + 4)
                right -= value_w
                label(value, right, y + 4, 14, DIM, value_w, RIGHT)
                right -= 8

            pen = FAINT if r.get("dim") else TEXT if i == index else DIM
            label(r["name"], x, y + 4, 15, pen, right - x)

        # Scroll hint when the list runs past the screen
        if len(rows) > LIST_ROWS:
            span = LIST_ROWS * LIST_ROW
            h = max(12, span * LIST_ROWS / len(rows))
            y = LIST_TOP + (span - h) * top / (len(rows) - LIST_ROWS)
            screen.pen = FAINT
            screen.rectangle(W - 4, int(y), 2, int(h))

    footer(labels)
    if hint:
        label(hint, BUTTON_X[1] - 60, FOOT_Y + 8, 9, DIM, 120, CENTER)


def bubble(text):
    # A big letter in the middle of the screen while jumping through a list
    screen.pen = ACCENT
    screen.shape(shape.rounded_rectangle(W / 2 - 32, 80, 64, 64, 12))
    label(text, W / 2 - 32, 92, 36, BG, 64, CENTER)


def toast(text):
    # A short confirmation just above the footer
    w = min(W - 40, _width(text, 13) + 28)
    x = (W - w) / 2
    y = FOOT_Y - 46
    screen.pen = ACCENT
    screen.shape(shape.rounded_rectangle(x, y, w, 26, 13))
    label(text, x + 14, y + 5, 13, BG, w - 28, CENTER)


def message(title, body="", pen=TEXT, busy=False):
    screen.pen = PANEL
    screen.shape(shape.rounded_rectangle(20, 60, W - 40, 120, 10))
    label(title + (_dots() if busy else ""), 36, 78, 18, pen, W - 72)
    y = 108
    for line in body.split("\n"):
        for wrapped in wrap(line, 13, W - 72, 2):
            label(wrapped, 36, y, 13, DIM, W - 72)
            y += 18


def _dots():
    return "." * (1 + (badge.ticks // 400) % 3)
