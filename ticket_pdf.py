"""E-ticket PDF with QR code (reportlab) - upgraded from rail.py's Ticket.pdf."""
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

def build_ticket(t):
    """t: dict with pnr, train_no, train_name, date, cls, from/to (code,name,time), fare, passengers[]."""
    buf, st = io.BytesIO(), getSampleStyleSheet()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"Ticket {t['pnr']}", leftMargin=18*mm, rightMargin=18*mm, topMargin=15*mm)
    navy = colors.HexColor("#1b2a49")
    el = [Paragraph("<b>RailMind - E-Ticket</b>", st["Title"]),
          Paragraph(f"<b>PNR: {t['pnr']}</b> &nbsp;&nbsp; Status: <b>{t['status']}</b>", st["Heading2"]), Spacer(1, 6)]
    info = [["Train", f"{t['train_no']} - {t['train_name']}"], ["Class", t["cls"]], ["Journey date", t["date"]],
            ["Boarding station", f"{t['from_name']} ({t['from_code']})   Dep {t['dep_time']}"],
            ["Dropping station", f"{t['to_name']} ({t['to_code']})   Arr {t['arr_time']}"],
            ["Total fare", f"Rs. {t['fare']:.2f}"]]
    tb = Table(info, colWidths=[40*mm, 125*mm])
    tb.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .5, colors.grey), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8edf7")),
                            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold")]))
    rows = [["#", "Passenger", "Age/Sex", "Coach", "Seat", "Berth", "Status"]]
    for i, p in enumerate(t["passengers"], 1):
        rows.append([i, p["name"], f"{p['age']}/{p['gender']}", p["coach"] or "-", p["seat_no"] or "-", p["berth"] or "-",
                     p["status"] if p["status"] == "CNF" else f"WL/{p['wl_no']}"])
    pt = Table(rows, colWidths=[8*mm, 55*mm, 22*mm, 20*mm, 15*mm, 28*mm, 20*mm])
    pt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                            ("GRID", (0, 0), (-1, -1), .5, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    data = f"PNR:{t['pnr']}|{t['train_no']}|{t['from_code']}-{t['to_code']}|{t['date']}|{t['cls']}|" + \
           ",".join(f"{p['coach']}/{p['seat_no']}" for p in t["passengers"])
    w = qr.QrCodeWidget(data); b = w.getBounds(); s = 110
    d = Drawing(s, s, transform=[s/(b[2]-b[0]), 0, 0, s/(b[3]-b[1]), 0, 0]); d.add(w)
    el += [tb, Spacer(1, 10), Paragraph("<b>Passenger details</b>", st["Heading3"]), pt, Spacer(1, 12), d, Spacer(1, 6),
           Paragraph("Carry a valid photo ID. Waitlisted (WL) tickets are confirmed only if the status becomes CNF at chart preparation. "
                     "Sample project ticket - not valid for travel.", st["Italic"])]
    doc.build(el); return buf.getvalue()
