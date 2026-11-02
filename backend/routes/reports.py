# backend/routes/reports.py
import io
import csv
import datetime
from flask import Blueprint, request, jsonify, send_file
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from backend.services.ledger import verify_chain, get_title_chain
from backend.services.auth import get_current_user
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")

@reports_bp.route("/plot/<plot_id>/history", methods=["GET"])
def plot_history_report(plot_id: str):
    format_type = request.args.get("format", "json").lower()
    verification = verify_chain(plot_id=plot_id)
    chain = get_title_chain(plot_id)
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Fetch plot details
    street = "123 MG Road"
    city = "Bengaluru"
    status = "Clear"
    current_owner = "Unknown"

    if is_mock_mode():
        p = mock_db.plots.get(plot_id)
        if p:
            street = p.get("street_address", street)
            city = p.get("city", city)
        reg = next((r for r in mock_db.registry.values() if r["plot_id"] == plot_id), None)
        if reg:
            status = reg.get("legal_status", status)
            current_owner = reg.get("current_owner_id", current_owner)
    else:
        try:
            with get_pg_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT street_address, city, status, owner_id FROM v_plot_market WHERE plot_id = %s;",
                        (plot_id,)
                    )
                    r = cur.fetchone()
                    if r:
                        street, city, status, current_owner = r[0], r[1], r[2], r[3]
        except Exception:
            pass

    # 1. Export as CSV
    if format_type == "csv":
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(["Plot ID", plot_id])
        cw.writerow(["Address", f"{street}, {city}"])
        cw.writerow(["Legal Status", status])
        cw.writerow(["Current Owner ID", current_owner])
        cw.writerow(["Report Generated At", generated_at])
        cw.writerow(["Cryptographic Integrity", "PASS" if verification["verified"] else "FAIL"])
        cw.writerow([])
        cw.writerow(["Block #", "Type", "Seller ID", "Buyer ID", "Price (INR)", "Timestamp", "Transaction Hash (tx_id)", "Previous Hash"])
        for b in chain:
            cw.writerow([
                b.get("block_number"),
                b.get("block_type"),
                b.get("seller_id") or "N/A",
                b.get("buyer_id"),
                b.get("sale_price") or 0.0,
                b.get("timestamp"),
                b.get("tx_id"),
                b.get("prev_tx_hash")
            ])
        output = io.BytesIO()
        output.write(si.getvalue().encode('utf-8'))
        output.seek(0)
        return send_file(output, mimetype="text/csv", as_attachment=True, download_name=f"plot_{plot_id}_history.csv")

    # 2. Export as PDF via ReportLab
    if format_type == "pdf":
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = ParagraphStyle(
            'ReportTitle',
            parent=styles['Heading1'],
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#1e293b")
        )
        elements.append(Paragraph("Land Exchange: Cryptographic Title History", title_style))
        elements.append(Paragraph(f"<b>Plot ID:</b> {plot_id} | <b>Location:</b> {street}, {city}", styles['Normal']))
        elements.append(Paragraph(f"<b>Legal Status:</b> {status} | <b>Current Owner:</b> {current_owner}", styles['Normal']))
        elements.append(Paragraph(f"<b>Generated At:</b> {generated_at}", styles['Normal']))
        elements.append(Spacer(1, 12))

        # Integrity Badge
        ver_color = "#16a34a" if verification["verified"] else "#dc2626"
        ver_text = f"<font color='{ver_color}'><b>CRYPTOGRAPHIC VERIFICATION: {'PASS' if verification['verified'] else 'FAIL'}</b></font>"
        elements.append(Paragraph(ver_text, styles['Heading2']))
        if not verification["verified"]:
            elements.append(Paragraph(f"<b>Audit Failure:</b> {verification.get('error')}", styles['Normal']))
        elements.append(Spacer(1, 14))

        # Table data
        table_data = [["Block #", "Type", "Seller", "Buyer", "Price (INR)", "Date", "Tx Hash (short)"]]
        for b in chain:
            tx_short = (b.get("tx_id") or "")[:12] + "..."
            table_data.append([
                str(b.get("block_number")),
                b.get("block_type"),
                (b.get("seller_id") or "N/A")[:10],
                (b.get("buyer_id") or "")[:10],
                f"{b.get('sale_price', 0):,.2f}" if b.get('sale_price') else "0.00",
                (b.get("timestamp") or "")[:10],
                tx_short
            ])

        t = Table(table_data, colWidths=[45, 55, 65, 65, 80, 65, 95])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ]))
        elements.append(t)

        doc.build(elements)
        buffer.seek(0)
        return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"plot_{plot_id}_title_history.pdf")

    # Default JSON
    return jsonify({
        "plot_id": plot_id,
        "street_address": street,
        "city": city,
        "legal_status": status,
        "current_owner_id": current_owner,
        "generated_at": generated_at,
        "verification": verification,
        "chain": chain
    }), 200
