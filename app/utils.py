# app/utils.py
import os
from django.conf import settings
from django.utils.timezone import now
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from app.models import Payment, BillingInfo

def generate_ticket_pdf(booking):
    tickets_dir = os.path.join(settings.MEDIA_ROOT, 'tickets')
    os.makedirs(tickets_dir, exist_ok=True)  # ensures folder exists

    file_path = os.path.join(tickets_dir, f'ticket_{booking.id}.pdf')
    c = canvas.Canvas(file_path, pagesize=A4)
    page_w, page_h = A4

    payment = Payment.objects.filter(booking=booking).order_by('-id').first()
    billing = BillingInfo.objects.filter(booking=booking).order_by('-id').first()

    full_name = (booking.user.get_full_name() or '').strip()
    username_value = (booking.user.username or '').strip()
    user_email = (booking.user.email or '').strip()
    passenger_name = full_name or username_value or user_email or f"Passenger {booking.id}"
    email_value = billing.email if billing else user_email
    phone_value = (
        (payment.phone if payment else None)
        or (billing.phone if billing else None)
        or getattr(booking.user, 'phone', '')
        or ''
    )
    class_type_value = booking.class_type.name if getattr(booking, 'class_type', None) else ''
    pay_method_value = payment.pay_method if payment else 'MPesa'
    trxid_value = payment.trxid if payment else 'Pending'
    pay_status_value = payment.status if payment else 'Paid'
    passenger_total = (booking.passengers_adult or 0) + (booking.passengers_child or 0)
    selected_seats_value = booking.selected_seats or "-"
    booking_status_value = "Booked" if booking.status == "Accepted" else (booking.status or "Pending")

    def draw_field(x, y, w, h, label, value):
        c.setLineWidth(1)
        c.rect(x, y, w, h)
        c.setFont("Helvetica", 8)
        c.drawString(x + 6, y + h - 12, label)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 6, y + 8, str(value if value is not None else ""))

    # Header
    c.setFillColorRGB(0.1, 0.45, 0.25)
    c.rect(36, page_h - 88, page_w - 72, 40, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(48, page_h - 73, "Railway Ticket")
    c.setFont("Helvetica", 10)
    c.drawString(page_w - 150, page_h - 73, "Passenger Copy")
    c.setFillColorRGB(0, 0, 0)

    left = 36
    top = page_h - 110
    row_h = 36
    gap = 8
    full_w = page_w - 72

    # Row 1
    y = top - row_h
    draw_field(left, y, full_w / 3 - gap, row_h, "Booking ID", booking.id)
    draw_field(left + full_w / 3, y, full_w / 3 - gap, row_h, "Booking Date", booking.booking_date or booking.created_at.date())
    draw_field(left + (2 * full_w / 3), y, full_w / 3, row_h, "Booking Status", booking_status_value)

    # Row 2
    y -= (row_h + gap)
    draw_field(left, y, full_w / 2 - gap, row_h, "Passenger Name", passenger_name)
    draw_field(left + full_w / 2, y, full_w / 2, row_h, "Email", email_value)

    # Row 3
    y -= (row_h + gap)
    draw_field(left, y, full_w / 2 - gap, row_h, "Phone", phone_value)
    draw_field(left + full_w / 2, y, full_w / 2, row_h, "Train Name", booking.train_name)

    # Row 4
    y -= (row_h + gap)
    draw_field(left, y, full_w / 2 - gap, row_h, "From", booking.source)
    draw_field(left + full_w / 2, y, full_w / 2, row_h, "To", booking.destination)

    # Row 5
    y -= (row_h + gap)
    draw_field(left, y, full_w / 3 - gap, row_h, "Travel Date", booking.travel_date)
    draw_field(left + full_w / 3, y, full_w / 3 - gap, row_h, "Departure Time", booking.departure_time)
    draw_field(left + (2 * full_w / 3), y, full_w / 3, row_h, "Arrival Time", booking.arrival_time)

    # Row 6
    y -= (row_h + gap)
    quarter = full_w / 4
    draw_field(left, y, quarter - gap, row_h, "Class Type", class_type_value)
    draw_field(left + quarter, y, quarter - gap, row_h, "Adults", booking.passengers_adult or 0)
    draw_field(left + (2 * quarter), y, quarter - gap, row_h, "Children", booking.passengers_child or 0)
    draw_field(left + (3 * quarter), y, quarter, row_h, "Total Passengers", passenger_total)

    # Row 7
    y -= (row_h + gap)
    draw_field(left, y, full_w, row_h, "Seat Number(s)", selected_seats_value)

    # Row 8
    y -= (row_h + gap)
    draw_field(left, y, quarter - gap, row_h, "Total Fare (KES)", booking.total_fare)
    draw_field(left + quarter, y, quarter - gap, row_h, "Payment Method", pay_method_value)
    draw_field(left + (2 * quarter), y, quarter - gap, row_h, "Transaction Code", trxid_value)
    draw_field(left + (3 * quarter), y, quarter, row_h, "Payment Status", pay_status_value)

    c.setFont("Helvetica", 9)
    c.drawString(36, 40, f"Generated On: {now().strftime('%Y-%m-%d %H:%M:%S')}")
    c.save()

    return file_path
