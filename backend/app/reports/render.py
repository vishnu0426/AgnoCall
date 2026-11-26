"""The report itself: the Analytics numbers as a CSV and as a PDF."""
import csv
import io
from xml.sax.saxutils import escape

from app.schemas.schemas import AnalyticsOverview

KPI_LABELS = [
    ("processed_calls", "Conversations scored", ""),
    ("avg_qa_score", "Average AI QA score", ""),
    ("avg_health_score", "Average health score", ""),
    ("negative_end_percent", "Negative endings", "%"),
    ("avg_duration_seconds", "Average duration", "s"),
    ("follow_up_required", "Follow-ups", ""),
    ("needs_attention", "Not resolved (escalated, unresolved, callback)", ""),
]


def previous_kpis(o: AnalyticsOverview):
    """The previous period, but only if it had conversations: "up 29" against an empty period says nothing."""
    return o.kpis_previous if o.kpis_previous and o.kpis_previous.get("processed_calls") else None


def period_label(days: int | None) -> str:
    return f"Last {days} days" if days else "All time"


def _csv_safe(value) -> str:
    s = "" if value is None else str(value)
    # a cell starting with = + - @ would be run as a formula by a spreadsheet
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _fmt(key: str, value, unit: str) -> str:
    if value is None:
        return "-"
    if key == "avg_duration_seconds":
        m, s = divmod(int(value), 60)
        return f"{m}m {s:02d}s" if m else f"{s}s"
    return f"{value}{unit}" if unit == "%" else str(value)


def _change(key: str, cur, prev) -> str:
    if cur is None or prev is None or key == "avg_duration_seconds":
        return ""
    d = cur - prev
    return "no change" if abs(d) < 0.05 else f"{'+' if d > 0 else ''}{d:.1f}".rstrip("0").rstrip(".")


def quality_sentence(o: AnalyticsOverview) -> str:
    q = o.quality
    share = round(100 * q["conversations"] / q["processed"]) if q["processed"] else 0
    s = (f"{q['conversations']} of {q['processed']} processed recordings ({share}%) are real conversations and are "
         f"scored. {q['excluded']} were left out (IVR surveys, silent or very short calls: under "
         f"{q['min_words']} words or {q['min_seconds']} seconds).")
    if q["failed"]:
        s += f" {q['failed']} recordings failed to process and are not counted."
    return s


def build_csv(o: AnalyticsOverview, name: str, generated: str) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([_csv_safe(name)])
    w.writerow(["Period", period_label(o.days)])
    w.writerow(["Generated", generated])
    w.writerow([])
    prev = previous_kpis(o)
    w.writerow(["Metric", "Value", "Previous period" if prev else ""])
    for key, label, unit in KPI_LABELS:
        w.writerow([label, o.kpis.get(key), prev.get(key) if prev else ""])
    q = o.quality
    w.writerow([])
    w.writerow(["Data quality"])
    for label, key in [("Processed recordings", "processed"), ("Real conversations (scored)", "conversations"),
                       ("Left out (IVR / silent / very short)", "excluded"),
                       ("Scored calls with speech from one side only", "one_sided"),
                       ("Scored calls with roles from recording channel", "roles_from_channel"),
                       ("Failed recordings", "failed")]:
        w.writerow([label, q[key]])
    w.writerow([])
    w.writerow(["Category", "Calls", "Average QA", "Average sentiment"])
    for c in o.category_stats:
        w.writerow([_csv_safe(c.category), c.count, c.avg_qa, c.avg_sentiment])
    w.writerow([])
    w.writerow(["Term", "Calls", "Average sentiment"])
    for k in o.keywords[:25]:
        w.writerow([_csv_safe(k.keyword), k.count, k.avg_sentiment])
    if o.sentiment_trend:
        w.writerow([])
        w.writerow(["Day", "Positive", "Neutral", "Negative"])
        for d in o.sentiment_trend:
            w.writerow([d.day, d.positive, d.neutral, d.negative])
    if o.emotion_distribution:
        w.writerow([])
        w.writerow(["Customer emotion", "Calls"])
        for emotion, n in o.emotion_distribution.items():
            w.writerow([_csv_safe(emotion), n])
    cal = o.qa_calibration
    w.writerow([])
    w.writerow(["QA calibration (AI vs human reviewers)"])
    w.writerow(["Reviewed calls", cal.reviewed_calls])
    w.writerow(["Agreement within 10 points (%)", cal.agreement_percent])
    w.writerow(["Average difference (points)", cal.mean_abs_delta])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")        # BOM so Excel opens it as UTF-8


# (key, label, unit, higher is better)
TILES = [
    ("processed_calls", "Conversations scored", "", True),
    ("avg_qa_score", "Avg AI QA score", "", True),
    ("avg_health_score", "Avg health score", "", True),
    ("negative_end_percent", "Negative endings", "%", False),
    ("avg_duration_seconds", "Avg duration", "", None),
    ("follow_up_required", "Follow-ups", "", False),
    ("needs_attention", "Not resolved", "", False),
]


def build_pdf(o: AnalyticsOverview, name: str, generated: str) -> bytes:
    """The Analytics page as a document: metrics, categories, topics, sentiment, emotions, call volume,
    agent scores and AI-vs-reviewer calibration (charts drawn in app/reports/charts.py)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from app.reports import charts

    ink, muted, hair, accent = (colors.HexColor(c) for c in (charts.INK, charts.MUTED, charts.HAIR, "#2F6FED"))
    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=0, textColor=ink, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=ink, spaceBefore=12, spaceAfter=5)
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=ink)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11.5, textColor=muted)
    tile = ParagraphStyle("tile", parent=body, fontSize=8, leading=11)
    tile_label = ParagraphStyle("tile_label", parent=tile, fontSize=7.5, leading=10, textColor=colors.HexColor(charts.FAINT))
    tile_value = ParagraphStyle("tile_value", parent=tile, fontName="Helvetica-Bold", fontSize=17, leading=22)

    def tile_cell(label, value, change=""):
        return [Paragraph(escape(label.upper()), tile_label), Paragraph(escape(value), tile_value), Paragraph(change or "&nbsp;", tile)]

    def section(title, *flowables, note=None):
        parts = [Paragraph(escape(title), h2), *flowables]
        if note:
            parts.append(Paragraph(escape(note), small))
        return KeepTogether(parts)

    def table(rows, widths):
        tb = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
        tb.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), muted), ("TEXTCOLOR", (0, 1), (-1, -1), ink),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, accent), ("LINEBELOW", (0, 1), (-1, -1), 0.4, hair),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return tb

    q, prev = o.quality, previous_kpis(o)
    story = [
        Paragraph(escape(name), h1),
        Paragraph(f"{escape(period_label(o.days))} &nbsp;|&nbsp; generated {escape(generated)}", small),
        Spacer(1, 8), Paragraph(escape(quality_sentence(o)), body),
    ]
    if q["conversations"]:
        pct = round(100 * q["roles_from_channel"] / q["conversations"])
        story += [Spacer(1, 4), Paragraph(
            f"Agent and customer were told apart by recording channel on {pct}% of scored calls. "
            "Mono recordings are a best guess, which affects every agent score.", small)]

    # --- key metrics: tiles, with the change against the previous period when there is one
    cells = []
    for key, label, unit, higher in TILES:
        value = o.kpis.get(key)
        change = ""
        if prev and value is not None and prev.get(key) is not None and key != "avg_duration_seconds":
            diff = value - prev[key]
            if abs(diff) < 0.05:
                change = f'<font color="{charts.FAINT}">no change vs previous</font>'
            else:
                good = (diff > 0) == higher
                change = (f'<font color="{charts.HIGH if good else charts.LOW}">{diff:+.1f}'.replace(".0", "")
                          + f' vs previous</font>')
        cells.append(tile_cell(label, _fmt(key, value, unit), change))
    pct_roles = round(100 * q["roles_from_channel"] / q["conversations"]) if q["conversations"] else None
    cells.append(tile_cell("Roles confirmed", "-" if pct_roles is None else f"{pct_roles}%",
                           f'<font color="{charts.FAINT}">by recording channel</font>'))
    grid = Table([cells[:4], cells[4:8]], colWidths=[43.5 * mm] * 4, hAlign="LEFT", rowHeights=[21 * mm, 21 * mm])
    grid.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, hair), ("INNERGRID", (0, 0), (-1, -1), 0.5, hair),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(section("Key metrics", grid))

    # --- categories: bar per category, colour = how customers leave the call
    if o.category_stats:
        rows = [(c.category.title(), c.count, charts.sentiment_fill(c.avg_sentiment),
                 f"{c.count} call{'s' if c.count != 1 else ''}" + ("" if c.avg_qa is None else f", avg QA {c.avg_qa:g}"))
                for c in o.category_stats[:10]]
        story.append(section(
            "Categories", charts.bar_list(rows), charts.legend_gradient(charts.WIDTH, "negative", "positive sentiment",
                                                                         charts.LOW, charts.MID, charts.HIGH),
            note="Bar length is call volume. Colour is how customers leave the call."))

    # --- terms
    if o.keywords:
        def tone(avg):
            return charts.HIGH if (avg or 0) >= 0.15 else charts.LOW if (avg or 0) <= -0.15 else "#4B5468"
        rows = [(k.keyword, k.count, tone(k.avg_sentiment), f"{k.count} call{'s' if k.count != 1 else ''}")
                for k in o.keywords[:8]]
        story.append(section("What customers call about", charts.bar_list(rows),
                             note="Green: mostly positive calls. Red: mostly negative. Grey: neutral."))

    # --- sentiment trend and emotions
    if o.sentiment_trend:
        story.append(section(f"Sentiment trend (last {o.days or 30} days)", charts.sentiment_trend(o.sentiment_trend),
                             note="Calls per day by overall sentiment."))
    if o.emotion_distribution:
        rows = [(e.title(), n, "#2F6FED", str(n)) for e, n in list(o.emotion_distribution.items())[:10]]
        story.append(section("Customer emotions", charts.bar_list(rows, label_w=110),
                             note="Dominant customer emotion per call."))

    # --- volume and agent x criteria heatmaps
    if o.volume_heatmap:
        story.append(section("Call volume", charts.volume_grid(o.volume_heatmap),
                             note="When calls come in: weekday by hour of the day. Darker is busier."))
    if o.agent_criteria_heatmap:
        story.append(section("Agent x QA criteria", charts.criteria_grid(o.agent_criteria_heatmap),
                             note="Average AI score per criterion. Red cells are coaching targets, green are strengths."))

    # --- calibration
    cal = o.qa_calibration
    if cal.reviewed_calls:
        rows = [["Calls scored by a person", str(cal.reviewed_calls)],
                ["Agreement with the AI (within 10 points)", "-" if cal.agreement_percent is None else f"{cal.agreement_percent:g}%"],
                ["Average difference", "-" if cal.mean_abs_delta is None else f"{cal.mean_abs_delta:g} points"]]
        block = [table([["Measure", "Value"]] + rows, [120 * mm, 54 * mm])]
        if cal.by_criterion:
            block += [Spacer(1, 6), table(
                [["Criterion", "Reviewer minus AI", "Calls"]] + [
                    [c.criterion.replace("_", " ").title(), f"{c.avg_delta:+g}", str(c.n)] for c in cal.by_criterion],
                [90 * mm, 50 * mm, 34 * mm])]
        story.append(section("QA calibration (AI vs human reviewers)", *block,
                             note="A positive difference means reviewers score higher than the AI."))
    else:
        story.append(section("QA calibration (AI vs human reviewers)",
                             Paragraph("No calls have been scored by a person yet, so there is nothing to compare.", body)))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(muted)
        canvas.drawString(18 * mm, 10 * mm, "AgnoCall | AI call analysis")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                      bottomMargin=18 * mm, title=name, author="AgnoCall").build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
