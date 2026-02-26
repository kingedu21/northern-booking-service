import json
from decimal import Decimal

from django.contrib import admin
from django.db.models import Count, F, Sum
from django.db.models.fields import DateTimeField
from django.db.models.functions import TruncDate, TruncMonth
from django.template.response import TemplateResponse
from django.utils import timezone

from .ai_service import generate_admin_insights
from .models import Booking, Train


def _booking_field_names():
    return {field.name for field in Booking._meta.get_fields()}


def _completed_bookings():
    field_names = _booking_field_names()

    if 'payment_status' in field_names:
        return Booking.objects.filter(payment_status='Completed')

    if 'payment' in field_names:
        return Booking.objects.filter(payment__status='Completed').distinct()

    # Fallback for projects that use a different status name in Booking.
    if 'status' in field_names:
        return Booking.objects.filter(status='Completed')

    return Booking.objects.none()


def _revenue_field():
    field_names = _booking_field_names()
    if 'amount_paid' in field_names:
        return 'amount_paid'
    if 'total_fare' in field_names:
        return 'total_fare'
    return None


def _train_group_field():
    field_names = _booking_field_names()
    if 'train' in field_names:
        return 'train__name'
    if 'train_name' in field_names:
        return 'train_name'
    return None


def _booking_date_field():
    field_names = _booking_field_names()
    if 'booking_date' in field_names:
        return 'booking_date'
    if 'created_at' in field_names:
        return 'created_at'
    return None


def _is_datetime_field(field_name):
    if not field_name:
        return False
    try:
        return isinstance(Booking._meta.get_field(field_name), DateTimeField)
    except Exception:
        return False


def _analytics_payload():
    completed_bookings = _completed_bookings()
    revenue_field = _revenue_field()
    train_group_field = _train_group_field()
    booking_date_field = _booking_date_field()
    booking_date_is_datetime = _is_datetime_field(booking_date_field)

    total_bookings = completed_bookings.count()
    total_trains = Train.objects.count()
    total_revenue = (
        completed_bookings.aggregate(total=Sum(revenue_field)).get('total')
        if revenue_field
        else Decimal('0')
    ) or Decimal('0')

    today = timezone.localdate()
    if revenue_field and booking_date_field:
        today_lookup = (
            f'{booking_date_field}__date'
            if booking_date_is_datetime
            else booking_date_field
        )
        today_revenue = (
            completed_bookings
            .filter(**{today_lookup: today})
            .aggregate(total=Sum(revenue_field))
            .get('total')
        ) or Decimal('0')
    else:
        today_revenue = Decimal('0')

    if revenue_field and train_group_field:
        revenue_per_train_qs = (
            completed_bookings
            .values(train_label=F(train_group_field))
            .annotate(total_revenue=Sum(revenue_field), bookings=Count('id'))
            .order_by('-total_revenue')
        )
        revenue_per_train = list(revenue_per_train_qs)
    else:
        revenue_per_train = []

    if revenue_field and booking_date_field:
        monthly_revenue_qs = (
            completed_bookings
            .annotate(month=TruncMonth(booking_date_field))
            .values('month')
            .annotate(total_revenue=Sum(revenue_field))
            .order_by('month')
        )
        monthly_revenue = list(monthly_revenue_qs)
    else:
        monthly_revenue = []

    if booking_date_field:
        daily_bookings_qs = (
            completed_bookings
            .annotate(day=TruncDate(booking_date_field))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('day')
        )
        daily_bookings = list(daily_bookings_qs)
    else:
        daily_bookings = []

    return {
        'total_revenue': total_revenue,
        'total_bookings': total_bookings,
        'total_trains': total_trains,
        'today_revenue': today_revenue,
        'revenue_per_train': revenue_per_train,
        'monthly_revenue': monthly_revenue,
        'daily_bookings': daily_bookings,
    }


def dashboard_view(request):
    analytics = _analytics_payload()
    revenue_per_train = analytics['revenue_per_train']
    monthly_revenue = analytics['monthly_revenue']
    daily_bookings = analytics['daily_bookings']

    context = {
        **admin.site.each_context(request),
        'title': 'Revenue Analytics Dashboard',
        **analytics,
        'bar_labels_json': json.dumps([item.get('train_label') or 'Unknown' for item in revenue_per_train]),
        'bar_values_json': json.dumps([float(item.get('total_revenue') or 0) for item in revenue_per_train]),
        'line_labels_json': json.dumps([
            item['month'].strftime('%Y-%m') if item.get('month') else 'N/A'
            for item in monthly_revenue
        ]),
        'line_values_json': json.dumps([float(item.get('total_revenue') or 0) for item in monthly_revenue]),
        'pie_labels_json': json.dumps([item.get('train_label') or 'Unknown' for item in revenue_per_train]),
        'pie_values_json': json.dumps([float(item.get('total_revenue') or 0) for item in revenue_per_train]),
        'daily_labels_json': json.dumps([
            item['day'].strftime('%Y-%m-%d') if item.get('day') else 'N/A'
            for item in daily_bookings
        ]),
        'daily_values_json': json.dumps([int(item.get('count') or 0) for item in daily_bookings]),
    }
    return TemplateResponse(request, 'admin/dashboard.html', context)


def ai_insights_view(request):
    analytics = _analytics_payload()

    metrics = {
        "total_revenue": float(analytics["total_revenue"]),
        "today_revenue": float(analytics["today_revenue"]),
        "total_bookings": int(analytics["total_bookings"]),
        "total_trains": int(analytics["total_trains"]),
        "top_trains_by_revenue": [
            {
                "train": row.get("train_label") or "Unknown",
                "revenue": float(row.get("total_revenue") or 0),
                "bookings": int(row.get("bookings") or 0),
            }
            for row in analytics["revenue_per_train"][:10]
        ],
        "monthly_revenue": [
            {
                "month": row["month"].strftime("%Y-%m") if row.get("month") else "N/A",
                "revenue": float(row.get("total_revenue") or 0),
            }
            for row in analytics["monthly_revenue"]
        ],
        "daily_bookings": [
            {
                "day": row["day"].strftime("%Y-%m-%d") if row.get("day") else "N/A",
                "count": int(row.get("count") or 0),
            }
            for row in analytics["daily_bookings"]
        ],
    }

    ai_text, ai_error = generate_admin_insights(metrics)
    context = {
        **admin.site.each_context(request),
        'title': 'AI Insights',
        **analytics,
        'ai_insights': ai_text,
        'ai_error': ai_error,
    }
    return TemplateResponse(request, 'admin/ai_insights.html', context)
