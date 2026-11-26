"""
Charts for the PDF report, drawn with reportlab shapes so the PDF has the same analytics as the page:
categories, terms, sentiment trend, emotions, call volume, agent x criteria. Colours match the web page.
Only Helvetica (Standard 14) is used, so avoid characters outside basic Latin (no arrows or box symbols).
"""
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth

WIDTH = 493.0                       # A4 text width in points (174 mm)
INK, MUTED, FAINT, HAIR = "#171B24", "#5B6475", "#8B93A7", "#E2E5EC"
LOW, MID, HIGH = "#C1352E", "#E4E7ED", "#12805A"
SEQ = ["#E8EFFD", "#BDD3FA", "#8FB3F5", "#5E90F0", "#2F6FED", "#1D4FBF"]
POS, NEU, NEG = "#12805A", "#B7BDC9", "#C1352E"
FONT, BOLD = "Helvetica", "Helvetica-Bold"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHORT = {
    "greeting": "Greeting", "identity_verification": "ID check", "listening": "Listening", "empathy": "Empathy",
    "communication": "Comm.", "professionalism": "Prof.", "knowledge": "Know.", "resolution": "Resolve",
    "closing": "Closing",
}
CRITERIA_ORDER = list(SHORT)


def _rgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def lerp(a: str, b: str, t: float) -> str:
    pa, pb = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(pa, pb))


def sentiment_fill(avg):
    if avg is None:
        return MID
    t = max(-1.0, min(1.0, avg))
    return lerp(MID, LOW, -t) if t < 0 else lerp(MID, HIGH, t)


def score_fill(value: float, midpoint: float = 70, top: float = 100) -> str:
    if value <= midpoint:
        return lerp(MID, LOW, (midpoint - value) / midpoint)
    return lerp(MID, HIGH, (value - midpoint) / (top - midpoint))


def seq_fill(t: float) -> str:
    pos = max(0.0, min(1.0, t)) * (len(SEQ) - 1)
    i = min(int(pos), len(SEQ) - 2)
    return lerp(SEQ[i], SEQ[i + 1], pos - i)


def _ink_on(fill: str) -> str:
    r, g, b = (v / 255 for v in _rgb(fill))
    return INK if 0.299 * r + 0.587 * g + 0.114 * b > 0.6 else "#FFFFFF"


def _fit(text: str, width: float, size: float, font: str = FONT) -> str:
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "...", font, size) > width:
        text = text[:-1]
    return text + "..."


def _text(d, x, y, s, size=8, color=MUTED, font=FONT, anchor="start"):
    d.add(String(x, y, s, fontName=font, fontSize=size, fillColor=colors.HexColor(color), textAnchor=anchor))


def _rect(d, x, y, w, h, fill, stroke=None, radius=0):
    r = Rect(x, y, w, h, fillColor=colors.HexColor(fill), strokeColor=colors.HexColor(stroke) if stroke else None,
             strokeWidth=0.6 if stroke else 0)
    if radius:
        r.rx = r.ry = radius
    d.add(r)


def bar_list(rows: list[tuple[str, float, str, str]], width: float = WIDTH, label_w: float = 140,
             bar_h: float = 13, gap: float = 6) -> Drawing:
    """Horizontal bars. rows: (label, value, colour, text shown at the right of the bar)."""
    n = len(rows)
    h = n * (bar_h + gap) + 2
    d = Drawing(width, h)
    top = max((v for _, v, _, _ in rows), default=0) or 1
    track = width - label_w - 90
    for i, (label, value, color, right) in enumerate(rows):
        y = h - (i + 1) * (bar_h + gap) + gap / 2
        _text(d, 0, y + 3.5, _fit(label, label_w - 8, 8.5), 8.5, INK)
        _rect(d, label_w, y, max(2.0, track * value / top), bar_h, color, radius=2)
        _text(d, label_w + max(2.0, track * value / top) + 6, y + 3.5, right, 8, MUTED)
    return d


def sentiment_trend(trend, width: float = WIDTH, height: float = 130) -> Drawing:
    """One stacked column per day: positive / neutral / negative calls."""
    d = Drawing(width, height + 34)
    if not trend:
        return d
    left, bottom, plot_h = 26.0, 20.0, height - 6
    top = max((t.positive + t.neutral + t.negative) for t in trend) or 1
    n = len(trend)
    slot = (width - left) / n
    bw = min(22.0, slot * 0.7)
    for frac in (0, 0.5, 1):
        y = bottom + plot_h * frac
        d.add(Line(left, y, width, y, strokeColor=colors.HexColor(HAIR), strokeWidth=0.5))
        _text(d, left - 4, y - 3, f"{top * frac:g}", 7, FAINT, anchor="end")
    for i, t in enumerate(trend):
        x = left + i * slot + (slot - bw) / 2
        y = bottom
        for count, color in ((t.negative, NEG), (t.neutral, NEU), (t.positive, POS)):
            if count:
                seg = plot_h * count / top
                _rect(d, x, y, bw, seg, color)
                y += seg
        if n <= 12 or i % max(1, n // 10) == 0:
            _text(d, x + bw / 2, 8, f"{t.day[8:10]}/{t.day[5:7]}", 7, FAINT, anchor="middle")
    for j, (name, color) in enumerate((("Negative", NEG), ("Neutral", NEU), ("Positive", POS))):
        x = width - 150 + j * 52
        _rect(d, x, height + 22, 7, 7, color)
        _text(d, x + 10, height + 22.5, name, 7.5, MUTED)
    return d


def heat_grid(cells, rows: list[str], cols: list[str], col_labels: list[str], fill, label_w: float,
              show_values: bool, width: float = WIDTH, cell_h: float = 15, tick_every: int = 1) -> Drawing:
    """A labelled grid. `fill(value, max_value)` gives each cell's colour; missing cells stay empty."""
    values = {(c.row, c.col): c.value for c in cells if c.value is not None}
    top = max(values.values(), default=1) or 1
    cw = (width - label_w) / max(1, len(cols))
    h = len(rows) * cell_h + 16
    d = Drawing(width, h)
    for ri, row in enumerate(rows):
        y = h - 12 - (ri + 1) * cell_h
        _text(d, label_w - 6, y + 4, _fit(row, label_w - 8, 8), 8, INK, anchor="end")
        for ci, col in enumerate(cols):
            v = values.get((row, col))
            x = label_w + ci * cw
            if v is None:
                _rect(d, x + 0.8, y + 0.8, cw - 1.6, cell_h - 1.6, "#F4F6FA")
                continue
            f = fill(v, top)
            _rect(d, x + 0.8, y + 0.8, cw - 1.6, cell_h - 1.6, f, radius=1.5)
            if show_values:
                _text(d, x + cw / 2, y + 4.2, f"{v:g}", 7.5, _ink_on(f), anchor="middle")
    for ci, label in enumerate(col_labels):
        if ci % tick_every == 0:
            _text(d, label_w + ci * cw + cw / 2, h - 9, _fit(label, cw + 4, 7), 7, FAINT, anchor="middle")
    return d


def volume_grid(cells, width: float = WIDTH) -> Drawing:
    cols = [str(h) for h in range(24)]
    return heat_grid(cells, WEEKDAYS, cols, cols, lambda v, top: seq_fill(v / top), 30, False, width, 14, tick_every=3)


def criteria_grid(cells, width: float = WIDTH) -> Drawing:
    present = {c.col for c in cells}
    cols = [c for c in CRITERIA_ORDER if c in present] + sorted(present - set(CRITERIA_ORDER))
    rows = sorted({c.row for c in cells})[:12]
    labels = [SHORT.get(c, c.replace("_", " ").title()) for c in cols]
    return heat_grid(cells, rows, cols, labels, lambda v, top: score_fill(v), 110, True, width, 17)


def legend_gradient(width: float, left_label: str, right_label: str, low: str, mid: str, high: str) -> Drawing:
    d = Drawing(width, 14)
    _text(d, 0, 3, left_label, 7.5, FAINT)
    x0 = stringWidth(left_label, FONT, 7.5) + 8
    steps = 30
    for i in range(steps):
        t = i / (steps - 1)
        c = lerp(low, mid, t * 2) if t < 0.5 else lerp(mid, high, (t - 0.5) * 2)
        _rect(d, x0 + i * 3, 2, 3.2, 8, c)
    _text(d, x0 + steps * 3 + 6, 3, right_label, 7.5, FAINT)
    return d
