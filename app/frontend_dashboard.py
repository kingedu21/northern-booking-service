import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, F, Sum
from django.db.models.fields import DateTimeField
from django.db.models.functions import TruncDate, TruncMonth
from django.shortcuts import render
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date

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


def _apply_date_filter(qs, field_name, start_date, end_date):
    if not field_name or (not start_date and not end_date):
        return qs
    filters = {}
    if start_date:
        filters[f"{field_name}__date__gte"] = start_date if isinstance(start_date, timezone.datetime) else start_date
    if end_date:
        filters[f"{field_name}__date__lte"] = end_date if isinstance(end_date, timezone.datetime) else end_date
    return qs.filter(**filters)


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


def _parse_date_range(request):
    start_raw = (request.GET.get("start") or "").strip()
    end_raw = (request.GET.get("end") or "").strip()
    start_date = parse_date(start_raw) if start_raw else None
    end_date = parse_date(end_raw) if end_raw else None
    return start_raw, end_raw, start_date, end_date


def _export_csv(rows, headers, filename):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write(",".join(headers) + "\n")
    for row in rows:
        response.write(",".join(str(row.get(col, "") or "") for col in headers) + "\n")
    return response


@login_required
@user_passes_test(_is_admin)
def frontend_admin_dashboard(request):
    start_raw, end_raw, start_date, end_date = _parse_date_range(request)
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

    if booking_date_field and (start_date or end_date):
        completed = _apply_date_filter(completed, booking_date_field, start_date, end_date)
        total_bookings = completed.count()
        total_revenue = _revenue_total(completed)

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

    payment_method_split = (
        completed.values("payment_method")
        .annotate(total_revenue=Sum("total_fare"), bookings=Count("id"))
        .order_by("-total_revenue")
    )
    payment_method_split = [
        {
            "method": row.get("payment_method") or "Unknown",
            "total_revenue": row.get("total_revenue") or 0,
            "bookings": row.get("bookings") or 0,
        }
        for row in payment_method_split
    ]

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

    payments_qs = Payment.objects.filter(status__iexact="Paid")
    if start_date or end_date:
        payments_qs = payments_qs.filter(
            created_at__date__gte=start_date if start_date else timezone.datetime.min.date(),
            created_at__date__lte=end_date if end_date else timezone.datetime.max.date(),
        )
    payments_by_day = (
        payments_qs.annotate(day=TruncDate("created_at"))
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
        "start_date": start_raw,
        "end_date": end_raw,
        "revenue_per_train": revenue_per_train,
        "monthly_revenue": list(monthly_revenue),
        "daily_bookings": list(daily_bookings),
        "payments_by_day": payments_by_day,
        "seat_utilization_by_train": seat_utilization_by_train,
        "seat_utilization_by_class": seat_utilization_by_class,
        "route_revenue": route_revenue,
        "payment_method_split": payment_method_split,
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
        "method_labels_json": json.dumps([row["method"] for row in payment_method_split]),
        "method_values_json": json.dumps([float(row["total_revenue"] or 0) for row in payment_method_split]),
    }
    return render(request, "admin_frontend/dashboard.html", context)


@login_required
@user_passes_test(_is_admin)
def frontend_admin_export(request):
    start_raw, end_raw, start_date, end_date = _parse_date_range(request)
    export_type = (request.GET.get("type") or "bookings").strip().lower()

    if export_type == "payments":
        qs = Payment.objects.all()
        if start_date or end_date:
            qs = qs.filter(
                created_at__date__gte=start_date if start_date else timezone.datetime.min.date(),
                created_at__date__lte=end_date if end_date else timezone.datetime.max.date(),
            )
        rows = [
            {
                "id": p.id,
                "booking_id": p.booking_id,
                "pay_amount": p.pay_amount,
                "pay_method": p.pay_method,
                "status": p.status,
                "created_at": p.created_at,
            }
            for p in qs.order_by("-id")[:1000]
        ]
        return _export_csv(rows, ["id", "booking_id", "pay_amount", "pay_method", "status", "created_at"], "payments.csv")

    if export_type == "routes":
        completed = _completed_bookings()
        booking_date_field = _booking_date_field()
        if booking_date_field and (start_date or end_date):
            completed = _apply_date_filter(completed, booking_date_field, start_date, end_date)
        route_rows = (
            completed.values("source", "destination")
            .annotate(total_revenue=Sum("total_fare"), bookings=Count("id"))
            .order_by("-total_revenue")
        )
        rows = [
            {
                "source": row.get("source") or "",
                "destination": row.get("destination") or "",
                "total_revenue": row.get("total_revenue") or 0,
                "bookings": row.get("bookings") or 0,
            }
            for row in route_rows
        ]
        return _export_csv(rows, ["source", "destination", "total_revenue", "bookings"], "routes.csv")

    if export_type == "seat-utilization":
        seat_utilization_by_class = _seat_utilization_by_class()
        seat_utilization, seat_utilization_by_train = _seat_utilization_snapshot()
        rows = []
        for row in seat_utilization_by_train:
            rows.append(
                {
                    "group": "train",
                    "name": row["train"],
                    "utilization_percent": round(row["utilization"] * 100, 1),
                }
            )
        for row in seat_utilization_by_class:
            rows.append(
                {
                    "group": "class",
                    "name": row["class_name"],
                    "utilization_percent": round(row["utilization"] * 100, 1),
                }
            )
        return _export_csv(rows, ["group", "name", "utilization_percent"], "seat_utilization.csv")

    completed = _completed_bookings()
    booking_date_field = _booking_date_field()
    if booking_date_field and (start_date or end_date):
        completed = _apply_date_filter(completed, booking_date_field, start_date, end_date)
    rows = [
        {
            "id": b.id,
            "user": b.user.username if b.user else "",
            "train_name": b.train_name,
            "source": b.source,
            "destination": b.destination,
            "status": b.status,
            "total_fare": b.total_fare,
            "created_at": b.created_at,
        }
        for b in completed.order_by("-id")[:1000]
    ]
    return _export_csv(
        rows,
        ["id", "user", "train_name", "source", "destination", "status", "total_fare", "created_at"],
        "bookings.csv",
    )
