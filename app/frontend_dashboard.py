import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, F, Sum
from django.db.models.fields import DateTimeField
from django.db.models.functions import TruncDate, TruncMonth
from django.shortcuts import render
from django.utils import timezone

from .models import Booking, Payment, Ticket, Train, SeatAllocation, TrainClassCapacity, ClassType


def _is_admin(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def _booking_field_names():
    return {field.name for field in Booking._meta.get_fields()}


def _booking_date_field():
    field_names = _booking_field_names()
    if "created_at" in field_names:
        return "created_at"
    if "booking_date" in field_names:
        return "booking_date"
    return None


def _is_datetime_field(field_name):
    if not field_name:
        return False
    try:
        return isinstance(Booking._meta.get_field(field_name), DateTimeField)
    except Exception:
        return False


def _completed_bookings():
    field_names = _booking_field_names()
    if "status" in field_names:
        return Booking.objects.filter(status__in=["Accepted", "Completed", "Paid"])
    return Booking.objects.none()


def _revenue_total(completed_qs):
    if "total_fare" in _booking_field_names():
        return completed_qs.aggregate(total=Sum("total_fare")).get("total") or Decimal("0")
    return Decimal("0")


def _seat_utilization_snapshot():
    allocations = (
        SeatAllocation.objects.values("train_id", "class_type_id", "travel_date")
        .annotate(allocated=Count("id"))
    )
    capacities = {
        (row["train_id"], row["class_type_id"]): int(row["seat_count"] or 0)
        for row in TrainClassCapacity.objects.values("train_id", "class_type_id", "seat_count")
    }

    utilization_rows = []
    for row in allocations:
        capacity = capacities.get((row["train_id"], row["class_type_id"]), 0)
        if capacity <= 0:
            continue
        utilization_rows.append(
            {
                "train_id": row["train_id"],
                "utilization": min(row["allocated"] / capacity, 1.0),
            }
        )

    if not utilization_rows:
        return 0.0, []

    total_utilization = sum(row["utilization"] for row in utilization_rows) / len(utilization_rows)

    per_train = {}
    for row in utilization_rows:
        per_train.setdefault(row["train_id"], []).append(row["utilization"])

    train_names = {train.id: train.name or f"Train {train.id}" for train in Train.objects.filter(id__in=per_train.keys())}
    per_train_rows = [
        {
            "train": train_names.get(train_id, f"Train {train_id}"),
            "utilization": sum(values) / len(values),
        }
        for train_id, values in per_train.items()
    ]
    per_train_rows.sort(key=lambda item: item["utilization"], reverse=True)
    return total_utilization, per_train_rows[:8]


def _seat_utilization_by_class():
    capacities = {
        row["class_type_id"]: int(row["capacity"] or 0)
        for row in TrainClassCapacity.objects.values("class_type_id").annotate(
            capacity=Sum("seat_count")
        )
    }
    allocations = {
        row["class_type_id"]: int(row["allocated"] or 0)
        for row in SeatAllocation.objects.values("class_type_id").annotate(
            allocated=Count("id")
        )
    }
    class_names = {
        row["id"]: row["name"]
        for row in ClassType.objects.values("id", "name")
    }

    rows = []
    for class_id, capacity in capacities.items():
        if capacity <= 0:
            continue
        allocated = allocations.get(class_id, 0)
        rows.append(
            {
                "class_name": class_names.get(class_id, f"Class {class_id}"),
                "utilization": min(allocated / capacity, 1.0),
            }
        )
    rows.sort(key=lambda item: item["utilization"], reverse=True)
    return rows[:8]


@login_required
@user_passes_test(_is_admin)
def frontend_admin_dashboard(request):
    completed = _completed_bookings()
    total_bookings = completed.count()
    total_revenue = _revenue_total(completed)

    total_paid_payments = Payment.objects.filter(status__iexact="Paid").count()
    failed_payments = Payment.objects.exclude(status__iexact="Paid").count()
    refunded_payments = Payment.objects.filter(status__in=["Refunded", "Refund", "refund"]).count()
    total_tickets = Ticket.objects.count()

    today = timezone.localdate()
    booking_date_field = _booking_date_field()
    booking_date_is_datetime = _is_datetime_field(booking_date_field)

    if booking_date_field:
        today_lookup = (
            f"{booking_date_field}__date"
            if booking_date_is_datetime
            else booking_date_field
        )
        today_revenue = (
            completed.filter(**{today_lookup: today})
            .aggregate(total=Sum("total_fare"))
            .get("total")
        ) or Decimal("0")
    else:
        today_revenue = Decimal("0")

    revenue_per_train = (
        completed.values(train_label=F("train_name"))
        .annotate(total_revenue=Sum("total_fare"), bookings=Count("id"))
        .order_by("-total_revenue")
    )
    revenue_per_train = list(revenue_per_train)

    if booking_date_field:
        monthly_revenue = (
            completed.annotate(month=TruncMonth(booking_date_field))
            .values("month")
            .annotate(total_revenue=Sum("total_fare"))
            .order_by("month")
        )
        daily_bookings = (
            completed.annotate(day=TruncDate(booking_date_field))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )
    else:
        monthly_revenue = []
        daily_bookings = []

    payments_by_day = (
        Payment.objects.filter(status__iexact="Paid")
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    payments_by_day = list(payments_by_day)[-14:]

    seat_utilization, seat_utilization_by_train = _seat_utilization_snapshot()
    seat_utilization_by_class = _seat_utilization_by_class()

    route_revenue = (
        completed.values("source", "destination")
        .annotate(total_revenue=Sum("total_fare"), bookings=Count("id"))
        .order_by("-total_revenue")[:10]
    )
    route_revenue = list(route_revenue)

    recent_bookings = (
        Booking.objects.select_related("user")
        .order_by("-id")[:8]
    )

    context = {
        "page_title": "Admin Dashboard",
        "total_revenue": total_revenue,
        "today_revenue": today_revenue,
        "total_bookings": total_bookings,
        "total_paid_payments": total_paid_payments,
        "failed_payments": failed_payments,
        "refunded_payments": refunded_payments,
        "total_tickets": total_tickets,
        "seat_utilization_percent": round(seat_utilization * 100, 1),
        "revenue_per_train": revenue_per_train,
        "monthly_revenue": list(monthly_revenue),
        "daily_bookings": list(daily_bookings),
        "payments_by_day": payments_by_day,
        "seat_utilization_by_train": seat_utilization_by_train,
        "seat_utilization_by_class": seat_utilization_by_class,
        "route_revenue": route_revenue,
        "recent_bookings": recent_bookings,
        "bar_labels_json": json.dumps([row.get("train_label") or "Unknown" for row in revenue_per_train]),
        "bar_values_json": json.dumps([float(row.get("total_revenue") or 0) for row in revenue_per_train]),
        "line_labels_json": json.dumps([
            row["month"].strftime("%Y-%m") if row.get("month") else "N/A"
            for row in monthly_revenue
        ]),
        "line_values_json": json.dumps([float(row.get("total_revenue") or 0) for row in monthly_revenue]),
        "daily_labels_json": json.dumps([
            row["day"].strftime("%Y-%m-%d") if row.get("day") else "N/A"
            for row in daily_bookings
        ]),
        "daily_values_json": json.dumps([int(row.get("count") or 0) for row in daily_bookings]),
        "payment_labels_json": json.dumps([
            row["day"].strftime("%Y-%m-%d") if row.get("day") else "N/A"
            for row in payments_by_day
        ]),
        "payment_values_json": json.dumps([int(row.get("count") or 0) for row in payments_by_day]),
        "seat_labels_json": json.dumps([row["train"] for row in seat_utilization_by_train]),
        "seat_values_json": json.dumps([round(row["utilization"] * 100, 1) for row in seat_utilization_by_train]),
        "class_labels_json": json.dumps([row["class_name"] for row in seat_utilization_by_class]),
        "class_values_json": json.dumps([round(row["utilization"] * 100, 1) for row in seat_utilization_by_class]),
        "route_labels_json": json.dumps([
            f"{row.get('source') or 'Unknown'} → {row.get('destination') or 'Unknown'}"
            for row in route_revenue
        ]),
        "route_values_json": json.dumps([float(row.get("total_revenue") or 0) for row in route_revenue]),
    }
    return render(request, "admin_frontend/dashboard.html", context)
