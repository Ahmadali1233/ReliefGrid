"""Reports of fulfilled and unfilled shelter requests, as JSON, CSV or PDF."""

import csv
import io
from datetime import datetime

from fpdf import FPDF

from ..services.dispatch import loads
from ..services.queries import requests_list, summary

COLUMNS = ["id", "shelter_id", "shelter_name", "item", "urgency", "quantity", "allocated", "remaining", "status",
           "dispatched", "delivered"]


def build():
    data = summary()
    reqs = requests_list()
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "headline": data["headline"],
        "totals": {
            "requests": len([r for r in reqs if r["status"] != "cancelled"]),
            "fulfilled": sum(1 for r in reqs if r["status"] == "fulfilled"),
            "partial": sum(1 for r in reqs if r["status"] == "partial"),
            "unfilled": sum(1 for r in reqs if r["status"] == "unfilled"),
            "cancelled": sum(1 for r in reqs if r["status"] == "cancelled"),
            "units_requested": data["kpis"]["units_requested"],
            "units_allocated": data["kpis"]["units_allocated"],
        },
        "integrity": f"{data['integrity']['passed']} of {data['integrity']['total']} checks passed",
        "unfilled_or_partial": [{c: r[c] for c in COLUMNS} for r in reqs if r["status"] in ("unfilled", "partial")],
        "fulfilled": [{c: r[c] for c in COLUMNS} for r in reqs if r["status"] == "fulfilled"],
        "stock": [{"item": s["item"], "unit": s["unit"], "in_stock": s["total"], "status": s["status"]}
                  for s in data["stock"]],
        "people": data["people"],
        "waybills": [{"waybill": l["waybill"], "status": {"dispatched": "on the way"}.get(l["status"], l["status"]),
                      "from": l["warehouse_name"], "to": l["shelter_name"],
                      "items": ", ".join(f"{i['quantity']:,} {i['item'].lower()}" for i in l["items"]),
                      "units": l["total"], "driver": l.get("dispatched_by"), "received_by": l.get("received_by"),
                      "missing": ", ".join(f"{x['quantity']:,} {x['item'].lower()} ({x['note']})" for x in l.get("lost", [])),
                      "delivered_at": l.get("delivered_at")}
                     for l in loads() if l["status"] != "allocated"],
    }


def to_csv(report):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    for row in report["unfilled_or_partial"] + report["fulfilled"]:
        w.writerow([row[c] for c in COLUMNS])
    return buf.getvalue()


def _latin(text):
    return str(text).replace("—", "-").replace("–", "-").replace("→", "->").encode("latin-1", "replace").decode("latin-1")


class _PDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.set_text_color(120, 125, 140)
        self.cell(0, 6, _latin(f"ReliefGrid · Team FEAST · page {self.page_no()}"), align="C")


def to_pdf(report):
    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()
    ink, muted, teal = (20, 24, 43), (95, 100, 118), (14, 124, 107)

    pdf.set_fill_color(15, 18, 34)
    pdf.rect(0, 0, 210, 34, "F")
    pdf.set_xy(14, 10)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 8, "ReliefGrid allocation report")
    pdf.set_xy(14, 19)
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(200, 205, 220)
    when = datetime.fromisoformat(report["generated_at"]).strftime("%d %b %Y, %H:%M")
    pdf.cell(0, 6, _latin(f"Generated {when} · {report['integrity']}"))

    pdf.set_xy(14, 42)
    pdf.set_text_color(*ink)
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, _latin(report["headline"]), new_x="LMARGIN", new_y="NEXT")
    t = report["totals"]
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(*muted)
    pdf.set_x(14)
    pdf.cell(0, 6, _latin(
        f"{t['requests']} requests · {t['fulfilled']} fulfilled · {t['partial']} partial · {t['unfilled']} unfilled · "
        f"{t['units_allocated']:,} of {t['units_requested']:,} units allocated"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    def table(title, rows):
        pdf.set_x(14)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*ink)
        pdf.cell(0, 8, _latin(f"{title} ({len(rows)})"), new_x="LMARGIN", new_y="NEXT")
        widths = [20, 58, 34, 22, 16, 16, 16]
        heads = ["ID", "Shelter", "Item", "Urgency", "Asked", "Got", "Short"]
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(*muted)
        pdf.set_x(14)
        for w, h in zip(widths, heads):
            pdf.cell(w, 6, h, align="R" if h in ("Asked", "Got", "Short") else "L")
        pdf.ln()
        pdf.set_draw_color(225, 228, 236)
        pdf.set_font("Helvetica", size=9)
        if not rows:
            pdf.set_x(14)
            pdf.set_text_color(*muted)
            pdf.cell(0, 7, "None.", new_x="LMARGIN", new_y="NEXT")
        for r in rows:
            pdf.set_x(14)
            pdf.line(14, pdf.get_y(), 196, pdf.get_y())
            pdf.set_text_color(*ink)
            vals = [r["id"], r["shelter_name"][:34], r["item"][:20], r["urgency"].title(),
                    f"{r['quantity']:,}", f"{r['allocated']:,}", f"{r['remaining']:,}"]
            for i, (w, v) in enumerate(zip(widths, vals)):
                if i == 6 and r["remaining"]:
                    pdf.set_text_color(179, 51, 15)
                pdf.cell(w, 7, _latin(v), align="R" if i >= 4 else "L")
            pdf.ln()
        pdf.ln(5)

    table("Waiting: unfilled or partly filled", report["unfilled_or_partial"])
    table("Fulfilled", report["fulfilled"])

    bills = report.get("waybills", [])
    pdf.set_x(14)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*ink)
    pdf.cell(0, 8, _latin(f"Waybills: trucks out and delivered ({len(bills)})"), new_x="LMARGIN", new_y="NEXT")
    widths, heads = [26, 44, 62, 50], ["Waybill", "To", "Load", "Status"]
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*muted)
    pdf.set_x(14)
    for w, h in zip(widths, heads):
        pdf.cell(w, 6, h)
    pdf.ln()
    pdf.set_font("Helvetica", size=9)
    for b in bills:
        pdf.set_x(14)
        pdf.line(14, pdf.get_y(), 196, pdf.get_y())
        pdf.set_text_color(*ink)
        status = (f"signed: {b['received_by']}" if b["status"] == "delivered" else f"on the way: {b['driver']}")
        for w, v in zip(widths, [b["waybill"], b["to"][:26], b["items"][:40], status[:32]]):
            pdf.cell(w, 7, _latin(v))
        pdf.ln()
        if b["missing"]:
            pdf.set_x(40)
            pdf.set_text_color(179, 51, 15)
            pdf.cell(0, 6, _latin(f"Missing: {b['missing']}"[:110]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    pdf.set_x(14)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*ink)
    pdf.cell(0, 8, "Stock left", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    for s in report["stock"]:
        pdf.set_x(14)
        pdf.set_text_color(*(teal if s["status"] == "ok" else (179, 51, 15)))
        label = {"ok": "", "low": "  (low)", "out": "  (out)"}[s["status"]]
        pdf.set_text_color(*ink)
        pdf.cell(60, 6, _latin(s["item"]))
        pdf.set_text_color(*((179, 51, 15) if s["status"] != "ok" else muted))
        pdf.cell(0, 6, _latin(f"{s['in_stock']:,} {s['unit']}{label}"), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
