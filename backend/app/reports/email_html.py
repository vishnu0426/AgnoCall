"""The HTML version of a report email (the plain-text version is always sent alongside it).

Built from tables and inline styles only: mail apps strip <style> blocks, scripts and inline SVG, and block
remote images, so the logo is drawn with table cells and nothing is fetched from outside."""
from xml.sax.saxutils import escape

_HEIGHTS = [4, 9, 14, 8, 16, 6, 11, 5]          # the same bars as the logo in the app's sidebar
INK, MUTED, FAINT, HAIR, ACCENT = "#1B2130", "#4B5468", "#8A93A6", "#E3E6EC", "#2F6FED"


def _logo() -> str:
    bars = "".join(
        f'<td valign="middle" style="padding:0 1px"><table role="presentation" cellpadding="0" cellspacing="0">'
        f'<tr><td width="3" height="{h * 2}" style="width:3px;height:{h * 2}px;line-height:{h * 2}px;font-size:1px;'
        f'background:{ACCENT if i % 3 == 0 else "#6C7488"};border-radius:2px">&nbsp;</td></tr></table></td>'
        for i, h in enumerate(_HEIGHTS))
    return (f'<table role="presentation" cellpadding="0" cellspacing="0"><tr><td valign="middle" style="padding-right:8px">'
            f'<table role="presentation" cellpadding="0" cellspacing="0"><tr>{bars}</tr></table></td>'
            f'<td valign="middle" style="font:600 18px Arial,Helvetica,sans-serif;color:{INK}">AgnoCall</td></tr></table>')


def _kpi(label: str, value: str) -> str:
    return (f'<td width="33%" valign="top" style="padding:12px 14px;border:1px solid {HAIR}">'
            f'<div style="font:12px Arial,sans-serif;color:{FAINT}">{escape(label)}</div>'
            f'<div style="font:600 22px Arial,sans-serif;color:{INK};margin-top:2px">{escape(value)}</div></td>')


def build_html(*, intro: str, title: str, period_line: str, quality: str, kpis: list[tuple[str, str]],
               attached: str, company: str, test: bool) -> str:
    paras = "".join(f'<p style="margin:0 0 12px">{escape(p)}</p>' for p in intro.split("\n\n") if p.strip())
    banner = (f'<div style="background:#FFF4E0;border:1px solid #F0C98A;color:#7A4B00;padding:10px 14px;margin-bottom:18px;'
              f'font:13px Arial,sans-serif">This is a <b>test</b> of a schedule that has not been saved. '
              f'Nothing is scheduled yet.</div>') if test else ""
    cells = "".join(_kpi(label, value) for label, value in kpis)
    co = escape(company)
    return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#F4F5F8">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F4F5F8"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#FFFFFF;border:1px solid {HAIR}">
<tr><td style="padding:20px 28px;border-bottom:1px solid {HAIR}">{_logo()}</td></tr>
<tr><td style="padding:24px 28px;font:14px/21px Arial,Helvetica,sans-serif;color:{INK}">
{banner}{paras}
<div style="font:600 17px Arial,sans-serif;margin:20px 0 2px">{escape(title)}</div>
<div style="font:13px Arial,sans-serif;color:{MUTED};margin-bottom:14px">{escape(period_line)}</div>
<p style="margin:0 0 16px;color:{MUTED}">{escape(quality)}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse"><tr>{cells}</tr></table>
<p style="margin:16px 0 0;color:{MUTED}">{escape(attached)}</p>
</td></tr>
<tr><td style="padding:16px 28px;border-top:1px solid {HAIR};background:#FAFBFC;font:12px/18px Arial,sans-serif;color:{FAINT}">
Sent automatically by AgnoCall for {co}. This report contains call data: please do not forward it outside {co}.<br>
Please do not reply to this message; the mailbox is not monitored.<br>
&copy; {co}
</td></tr></table></td></tr></table></body></html>"""
