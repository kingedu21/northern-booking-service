

from django.http import  HttpResponseBadRequest
from datetime import timezone as dt_timezone
import re


from django.shortcuts import render, redirect
from django.views import View
from app.models import CustomUser, Feedback, ContactForm, ContactNumber, Train, Station, ClassType, Booking, BookingDetail, BillingInfo, Payment, Ticket, SeatAllocation, TrainClassCapacity
from django.http import HttpResponse
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from app.forms import TrainForm
from django.contrib.auth import logout as auth_logout
from datetime import timezone, datetime, timedelta
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json
from datetime import datetime  # Make sure you have this
   
from django.contrib.auth.views import PasswordResetView
from django.urls import reverse_lazy
from django.contrib.messages.views import SuccessMessageMixin
import requests
from django.db import transaction, IntegrityError
from django.db.models import Count, Q, Sum
from urllib.parse import urlencode
from django.utils import timezone as dj_timezone

from django.shortcuts import render, redirect
from django.conf import settings
from django.core.cache import cache
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .models import MpesaTransaction
from .redis_lock import acquire_seat_locks
import base64

from django.views import View


# Create your views here.
timestamp = datetime.now()

# homepage view

class Home(View):
    def get(self, request):
        form = TrainForm
        daily_departures_count = Train.objects.filter(departure_time__isnull=False).count()
        major_stations_count = Station.objects.count()
        booking_counts = Booking.objects.aggregate(
            accepted=Count('id', filter=Q(status='Accepted')),
            canceled=Count('id', filter=Q(status='Canceled')),
        )
        accepted_bookings = booking_counts.get('accepted') or 0
        canceled_bookings = booking_counts.get('canceled') or 0
        finalized_bookings = accepted_bookings + canceled_bookings
        on_time_trips = (
            f"{(accepted_bookings / finalized_bookings) * 100:.1f}%"
            if finalized_bookings
            else "N/A"
        )

        timetable_trains = (
            Train.objects
            .select_related('source', 'destination')
            .annotate(total_capacity=Sum('class_capacities__seat_count'))
            .order_by('departure_time', 'name')[:6]
        )
        return render(request, 'home.html', {
            'form': form,
            'timetable_trains': timetable_trains,
            'home_stats': {
                'daily_departures': f"{daily_departures_count}+",
                'major_stations': major_stations_count,
                'on_time_trips': on_time_trips,
                'booking_access': "24/7",
            },
        })


from django.shortcuts import get_object_or_404


def get_class_seat_capacity(train, class_type):
    train_ids = _train_group_train_ids(train)
    capacities = list(
        TrainClassCapacity.objects
        .filter(train_id__in=train_ids, class_type=class_type)
        .values_list("seat_count", flat=True)
    )
    # Shared capacity group: use the highest configured capacity in the group.
    return int(max(capacities) if capacities else 0)


def _train_group_key(train):
    return train.seat_scope_key() if hasattr(train, "seat_scope_key") else f"train:{train.id}"


def _train_group_train_ids(train):
    group = (getattr(train, "capacity_group", "") or "").strip()
    if not group:
        return [int(train.id)]
    return list(
        Train.objects.filter(capacity_group__iexact=group).values_list("id", flat=True)
    ) or [int(train.id)]


def _train_group_key_from_id(train_id):
    row = Train.objects.filter(id=train_id).values("id", "capacity_group").first()
    if not row:
        return f"train:{train_id}"
    group = (row.get("capacity_group") or "").strip()
    if group:
        return f"group:{group.lower()}"
    return f"train:{int(train_id)}"


def get_available_seats(train, travel_date, class_type):
    total_seats = get_class_seat_capacity(train, class_type)
    if total_seats <= 0:
        return 0

    train_ids = _train_group_train_ids(train)
    taken = SeatAllocation.objects.filter(
        train_id__in=train_ids,
        class_type=class_type,
        travel_date=travel_date
    ).count()
    return max(total_seats - taken, 0)


def get_taken_seat_numbers(train, travel_date, class_type):
    train_ids = _train_group_train_ids(train)
    return set(
        SeatAllocation.objects.filter(
            train_id__in=train_ids,
            class_type=class_type,
            travel_date=travel_date
        )
        .values_list("seat_number", flat=True)
    )


def parse_selected_seats(raw_values):
    parsed = []
    for raw in raw_values:
        token = (raw or "").strip()
        if not token:
            continue
        if token.isdigit():
            parsed.append(int(token))
            continue
        for piece in token.split(","):
            piece = piece.strip()
            if piece:
                if not piece.isdigit():
                    return []
                parsed.append(int(piece))

    # keep order, remove duplicates
    seen = set()
    deduped = []
    for seat in parsed:
        if seat not in seen:
            deduped.append(seat)
            seen.add(seat)
    return deduped


def _cleanup_expired_unpaid_bookings():
    hold_seconds = int(getattr(settings, "UNPAID_BOOKING_HOLD_SECONDS", 60))
    if hold_seconds <= 0:
        return 0

    cutoff = dj_timezone.now() - timedelta(seconds=hold_seconds)
    stale_booking_ids = list(
        Booking.objects.filter(status="Pending", created_at__lte=cutoff)
        .exclude(payment__status__iexact="Paid")
        .values_list("id", flat=True)
        .distinct()
    )
    if not stale_booking_ids:
        return 0

    seat_tuples = list(
        SeatAllocation.objects.filter(booking_id__in=stale_booking_ids).values_list(
            "train_id", "class_type_id", "travel_date"
        )
    )

    # Free locked seats by removing allocations and stale bookings.
    SeatAllocation.objects.filter(booking_id__in=stale_booking_ids).delete()
    Booking.objects.filter(id__in=stale_booking_ids, status="Pending").delete()

    for train_id, class_type_id, travel_date in seat_tuples:
        if train_id and class_type_id and travel_date:
            _bump_availability_version(train_id, class_type_id, travel_date)

    return len(stale_booking_ids)


def _normalize_travel_date(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    parsed = parse_date(str(value))
    return parsed.isoformat() if parsed else str(value)


def _availability_version_key(train_scope, class_type_id, travel_date):
    date_token = _normalize_travel_date(travel_date)
    return f"seat_avail_version:{train_scope}:{class_type_id}:{date_token}"


def _get_availability_version(train_scope, class_type_id, travel_date):
    key = _availability_version_key(train_scope, class_type_id, travel_date)
    version = cache.get(key)
    if version is None:
        cache.set(key, 1, timeout=None)
        return 1
    try:
        return int(version)
    except (TypeError, ValueError):
        cache.set(key, 1, timeout=None)
        return 1


def _bump_availability_version(train_id, class_type_id, travel_date):
    train_scope = _train_group_key_from_id(train_id)
    key = _availability_version_key(train_scope, class_type_id, travel_date)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 2, timeout=None)


def _seat_availability_cache_key(travel_date, class_type_id, train_ids):
    ordered_ids = sorted({int(train_id) for train_id in train_ids})
    train_rows = Train.objects.filter(id__in=ordered_ids).values("id", "capacity_group")
    train_scope_map = {}
    for row in train_rows:
        group = (row.get("capacity_group") or "").strip()
        train_scope_map[int(row["id"])] = f"group:{group.lower()}" if group else f"train:{int(row['id'])}"

    scope_tokens = sorted({train_scope_map.get(train_id, f"train:{train_id}") for train_id in ordered_ids})
    versions = [str(_get_availability_version(scope, class_type_id, travel_date)) for scope in scope_tokens]
    return (
        f"seat_avail:v1:{_normalize_travel_date(travel_date)}:{class_type_id}:"
        f"{','.join(str(train_id) for train_id in ordered_ids)}:"
        f"{','.join(versions)}"
    )


def seat_availability(request):
    _cleanup_expired_unpaid_bookings()
    date_raw = (request.GET.get("date") or "").strip()
    class_type_raw = (request.GET.get("class_type") or "").strip()
    train_ids_raw = (request.GET.get("train_ids") or "").strip()

    travel_date = parse_date(date_raw)
    if not travel_date:
        return JsonResponse({"message": "Invalid or missing date."}, status=400)

    if not class_type_raw.isdigit():
        return JsonResponse({"message": "Invalid or missing class_type."}, status=400)
    class_type_id = int(class_type_raw)

    train_ids = []
    for token in train_ids_raw.split(","):
        token = token.strip()
        if token and token.isdigit():
            train_ids.append(int(token))
    train_ids = list(dict.fromkeys(train_ids))

    if not train_ids:
        return JsonResponse({"message": "No train ids provided."}, status=400)

    cache_key = _seat_availability_cache_key(travel_date, class_type_id, train_ids)
    cached_payload = cache.get(cache_key)
    if cached_payload is not None:
        return JsonResponse(cached_payload, status=200)

    trains = {int(train.id): train for train in Train.objects.filter(id__in=train_ids)}
    results = {}
    for train_id in train_ids:
        train = trains.get(int(train_id))
        if not train:
            results[str(train_id)] = {"available_seats": 0, "available_seat_numbers": []}
            continue
        capacity = get_class_seat_capacity(train, class_type_id)
        taken = get_taken_seat_numbers(train, travel_date, class_type_id)
        available_numbers = [
            seat_no for seat_no in range(1, capacity + 1)
            if seat_no not in taken
        ]
        results[str(train_id)] = {
            "available_seats": len(available_numbers),
            "available_seat_numbers": available_numbers,
        }

    payload = {"results": results}
    cache_ttl = getattr(settings, "SEAT_AVAILABILITY_CACHE_TTL_SECONDS", 30)
    cache.set(cache_key, payload, timeout=cache_ttl)
    return JsonResponse(payload, status=200)


def _find_station_by_text(raw_name):
    token = (raw_name or "").strip()
    if not token:
        return None
    return (
        Station.objects
        .filter(Q(name__icontains=token) | Q(code__icontains=token) | Q(place__icontains=token))
        .order_by('name')
        .first()
    )


def booking_assistant(request):
    if request.method not in ("GET", "POST"):
        return JsonResponse({"message": "Method not allowed."}, status=405)

    user_message = ""
    if request.method == "GET":
        user_message = (request.GET.get("q") or "").strip()
    else:
        try:
            body = json.loads(request.body or "{}")
            user_message = (body.get("message") or "").strip()
        except json.JSONDecodeError:
            return JsonResponse({"message": "Invalid JSON payload."}, status=400)

    if not user_message:
        return JsonResponse({
            "reply": "Ask me about routes, fares, or booking steps.",
            "suggestions": [
                "Show booking steps",
                "What are class fares?",
                "Trains from Nairobi to Mombasa",
            ],
        })

    text = user_message.lower()

    if ("how" in text and "book" in text) or "steps" in text or "process" in text:
        return JsonResponse({
            "reply": (
                "Booking steps:\n"
                "1) Select From, To, class type, date, and passengers on the home page.\n"
                "2) Click Book a Train to view available trains.\n"
                "3) Choose seats and confirm booking.\n"
                "4) Complete payment and download your ticket."
            ),
            "suggestions": [
                "What are class fares?",
                "Show popular routes",
            ],
        })

    if "fare" in text or "price" in text or "cost" in text:
        classes = list(ClassType.objects.order_by('name')[:10])
        if not classes:
            return JsonResponse({"reply": "No class fares configured yet."})

        adults = 1
        children = 0
        adult_match = re.search(r"(\d+)\s*adult", text)
        child_match = re.search(r"(\d+)\s*(child|children)", text)
        if adult_match:
            adults = int(adult_match.group(1))
        if child_match:
            children = int(child_match.group(1))

        selected = None
        for cls in classes:
            if cls.name and cls.name.lower() in text:
                selected = cls
                break
        if selected is None:
            selected = classes[0]

        lines = [
            f"- {cls.name}: adult {cls.effective_adult_price}, child {cls.effective_child_price}"
            for cls in classes
        ]
        estimate = selected.calculate_total_fare(adults, children)
        return JsonResponse({
            "reply": (
                "Current class fares:\n"
                + "\n".join(lines)
                + f"\n\nEstimated total for {adults} adult(s) and {children} child(ren) in {selected.name}: {estimate}"
            ),
            "suggestions": [
                "Show booking steps",
                "Trains from Nairobi to Mombasa",
            ],
        })

    route_match = re.search(r"from\s+(.+?)\s+to\s+(.+)", text)
    if route_match or "route" in text or "train" in text:
        source = destination = None
        if route_match:
            source = _find_station_by_text(route_match.group(1))
            destination = _find_station_by_text(route_match.group(2))

        if source and destination:
            trains = list(
                Train.objects
                .filter(source=source, destination=destination)
                .select_related("source", "destination")
                .order_by("departure_time", "name")[:6]
            )
            if not trains:
                return JsonResponse({
                    "reply": f"No trains found from {source.name} to {destination.name} right now.",
                    "suggestions": ["Try another route", "Show class fares"],
                })

            train_lines = []
            for train in trains:
                dep = train.departure_time.strftime("%H:%M") if train.departure_time else "TBA"
                arr = train.arrival_time.strftime("%H:%M") if train.arrival_time else "TBA"
                train_lines.append(f"- {train.name or 'Unnamed Train'} ({dep} - {arr})")

            return JsonResponse({
                "reply": (
                    f"Available trains from {source.name} to {destination.name}:\n"
                    + "\n".join(train_lines)
                    + "\n\nGo to the booking form section to pick date/class and continue."
                ),
                "link": "#book-train",
                "autofill": {
                    "source_name": source.name,
                    "destination_name": destination.name,
                },
                "suggestions": [
                    "What are class fares?",
                    "Show booking steps",
                ],
            })

        routes = (
            Train.objects
            .select_related("source", "destination")
            .exclude(source__isnull=True)
            .exclude(destination__isnull=True)
            .values_list("source__name", "destination__name")
            .distinct()[:8]
        )
        if routes:
            route_lines = [f"- {src} to {dst}" for src, dst in routes]
            return JsonResponse({
                "reply": "Popular routes:\n" + "\n".join(route_lines) + "\n\nAsk like: Trains from Nairobi to Mombasa",
                "suggestions": [
                    "Trains from Nairobi to Mombasa",
                    "What are class fares?",
                ],
            })

    return JsonResponse({
        "reply": (
            "I can help with routes, fares, and booking steps.\n"
            "Try: 'Trains from Nairobi to Mombasa', 'What are class fares?', or 'How do I book?'"
        ),
        "suggestions": [
            "How do I book?",
            "What are class fares?",
            "Trains from Nairobi to Mombasa",
        ],
    })

class AvailableTrain(View):
    def get(self, request):
        _cleanup_expired_unpaid_bookings()
        if not request.user.is_authenticated:
            messages.warning(request, "Please login first to book a train.")
            return redirect('login')

        if request.GET:
            rfrom = request.GET.get('rfrom')
            to = request.GET.get('to')
            date = request.GET.get('date')
            ctype = request.GET.get('ctype')
            adult = request.GET.get('pa')
            child = request.GET.get('pc')

            try:
                adult = int(adult)
                child = int(child)
            except (ValueError, TypeError):
                messages.warning(request, 'Invalid passenger input')
                return redirect('home')

            if not all([rfrom, to, date, ctype]) or rfrom == 'Select' or to == 'Select' or date in ['mm//dd//yyyy', '']:
                messages.warning(request, 'Please fill up the form properly')
                return redirect('home')

            if (adult + child) < 1:
                messages.warning(request, 'Please book at least 1 seat')
                return redirect('home')

            if (adult + child) > 5:
                messages.warning(request, 'You can book a maximum of 5 seats')
                return redirect('home')

            try:
                source = Station.objects.get(pk=rfrom)
                destination = Station.objects.get(pk=to)
                # Fix: Use get_object_or_404 or check for digit first
                if not ctype.isdigit():
                    messages.warning(request, 'Invalid class type')
                    return redirect('home')
                class_type = ClassType.objects.get(pk=int(ctype))
            except (Station.DoesNotExist, ClassType.DoesNotExist):
                messages.warning(request, 'Invalid station or class type')
                return redirect('home')

            schedule_key = f"schedule:v1:{source.id}:{destination.id}:{class_type.id}"
            train_ids = cache.get(schedule_key)
            if train_ids is None:
                train_ids = list(
                    Train.objects.filter(
                        source=source,
                        destination=destination,
                        class_type=class_type
                    )
                    .distinct()
                    .values_list("id", flat=True)
                )
                schedule_ttl = getattr(settings, "SCHEDULE_CACHE_TTL_SECONDS", 300)
                cache.set(schedule_key, train_ids, timeout=schedule_ttl)

            search = Train.objects.filter(id__in=train_ids).distinct()

            for train in search:
                class_capacity = get_class_seat_capacity(train, class_type)
                taken = get_taken_seat_numbers(train, date, class_type)
                train.available_seat_numbers = [
                    seat_no
                    for seat_no in range(1, class_capacity + 1)
                    if seat_no not in taken
                ]
                train.available_seats = len(train.available_seat_numbers)

            context = {
                'search': search,
                'source': source,
                'destination': destination,
                'class_type': class_type,
                'date': date,
                'pa': adult,
                'pc': child,
                'adult_fare': class_type.effective_adult_price,
                'child_fare': class_type.effective_child_price,
                'quote_total_fare': class_type.calculate_total_fare(adult, child),
            }

            return render(request, 'available_train.html', context)

        else:
            messages.warning(request, 'Find a train first to view availability')
            return redirect('home')

#Booking page view
from django.utils import timezone

from django.views import View
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Booking, BookingDetail, BillingInfo, Payment, Ticket, ClassType, SeatAllocation
from datetime import timedelta
from django.shortcuts import get_object_or_404

class Bookings(View):
    def get(self, request):
        _cleanup_expired_unpaid_bookings()
        if request.GET:
            user = request.user
            if user.is_authenticated:
                train = request.GET.get('train')
                source = request.GET.get('source')
                destination = request.GET.get('destination')
                source_id = request.GET.get('source_id')
                destination_id = request.GET.get('destination_id')
                date = request.GET.get('date')
                departure = request.GET.get('departure')
                arrival = request.GET.get('arrival')
                train_id = request.GET.get('train_id')
                tp = request.GET.get('tp')
                pa = request.GET.get('pa')
                pc = request.GET.get('pc')
                ctype = request.GET.get('ctype')
                selected_seats = parse_selected_seats(request.GET.getlist('selected_seats'))

                def redirect_back_to_search(message_text, level="warning"):
                    print(
                        "[BOOKING][REDIRECT] "
                        f"reason={message_text!r}, "
                        f"user_id={getattr(user, 'id', None)}, "
                        f"train_id={train_id!r}, class_type_id={ctype!r}, date={date!r}, "
                        f"tp={tp!r}, pa={pa!r}, pc={pc!r}, selected_seats={selected_seats!r}"
                    )
                    level_map = {
                        "warning": messages.warning,
                        "error": messages.error,
                        "info": messages.info,
                        "success": messages.success,
                    }
                    notifier = level_map.get(level, messages.warning)
                    notifier(request, message_text)
                    if source_id and destination_id and date and ctype:
                        query = urlencode({
                            'rfrom': source_id,
                            'to': destination_id,
                            'date': date,
                            'ctype': ctype,
                            'pa': pa,
                            'pc': pc,
                        })
                        return redirect(f"{reverse('available_train')}?{query}")
                    return redirect('home')

                fare_each = get_object_or_404(ClassType, pk=ctype)

                train_obj = get_object_or_404(Train, pk=train_id)
                grouped_train_ids = _train_group_train_ids(train_obj)
                seat_scope = _train_group_key(train_obj)
                available_seat = get_available_seats(train_obj, date, fare_each)
                class_capacity = get_class_seat_capacity(train_obj, fare_each)

                tp = int(tp)
                pa = int(pa)
                pc = int(pc)
                if tp != (pa + pc):
                    return redirect_back_to_search("Passenger counts do not match the selected total.")
                if len(selected_seats) != tp:
                    return redirect_back_to_search(f"Please select exactly {tp} seat(s).")
                if any(seat < 1 or seat > class_capacity for seat in selected_seats):
                    return redirect_back_to_search("One or more selected seats are invalid.")

                if available_seat >= tp:
                    total_fare = fare_each.calculate_total_fare(pa, pc)

                    lock_ttl = getattr(settings, "SEAT_LOCK_TTL_SECONDS", 30)
                    with acquire_seat_locks(
                        train_id=seat_scope,
                        class_type_id=fare_each.id,
                        travel_date=_normalize_travel_date(date),
                        seat_numbers=selected_seats,
                        ttl_seconds=lock_ttl,
                    ) as (locks_ok, lock_conflicts):
                        if not locks_ok:
                            seat_text = ", ".join(str(s) for s in lock_conflicts)
                            return redirect_back_to_search(
                                f"Seat(s) {seat_text} are currently being processed by another user. Please retry.",
                                level="info",
                            )

                        try:
                            with transaction.atomic():
                                conflicting = set(
                                    SeatAllocation.objects.select_for_update()
                                    .filter(
                                        train_id__in=grouped_train_ids,
                                        class_type=fare_each,
                                        travel_date=date,
                                        seat_number__in=selected_seats
                                    )
                                    .values_list("seat_number", flat=True)
                                )
                                if conflicting:
                                    seat_text = ", ".join(str(s) for s in sorted(conflicting))
                                    return redirect_back_to_search(
                                        f"Seat(s) {seat_text} are no longer available. The list has been refreshed below.",
                                        level="info",
                                    )

                                booking = Booking.objects.create(
                                    user=user,
                                    source=source,
                                    destination=destination,
                                    travel_date=date,
                                    class_type=fare_each,
                                    passengers_adult=pa,
                                    passengers_child=pc,
                                    train_name=train,
                                    departure_time=departure,
                                    arrival_time=arrival,
                                    total_fare=total_fare,
                                    selected_seats=", ".join(str(seat) for seat in selected_seats),
                                )
                                SeatAllocation.objects.bulk_create(
                                    [
                                        SeatAllocation(
                                            train=train_obj,
                                            booking=booking,
                                            class_type=fare_each,
                                            travel_date=date,
                                            seat_number=seat,
                                        )
                                        for seat in selected_seats
                                    ]
                                )
                        except IntegrityError:
                            conflicting = set(
                                SeatAllocation.objects
                                .filter(
                                    train_id__in=grouped_train_ids,
                                    class_type=fare_each,
                                    travel_date=date,
                                    seat_number__in=selected_seats
                                )
                                .values_list("seat_number", flat=True)
                            )
                            if conflicting:
                                seat_text = ", ".join(str(s) for s in sorted(conflicting))
                                return redirect_back_to_search(
                                    f"Seat(s) {seat_text} were just taken. Updated availability is now shown.",
                                    level="info",
                                )
                            return redirect_back_to_search(
                                "Seat availability changed while booking. Updated availability is now shown.",
                                level="info",
                            )

                    _bump_availability_version(train_obj.id, fare_each.id, date)

                    return render(request, 'booking.html', {
                        'booking': booking,
                        'train': train,
                        'source': source,
                        'destination': destination,
                        'date': date,
                        'departure': departure,
                        'arrival': arrival,
                        'tp': tp,
                        'pa': pa,
                        'pc': pc,
                        'ctype': ctype,
                        'total_fare': total_fare,
                        'fare_each': fare_each,
                        'adult_fare': fare_each.effective_adult_price,
                        'child_fare': fare_each.effective_child_price,
                        'selected_seats': booking.selected_seats,
                    })
                else:
                    return redirect_back_to_search(f"Sorry! Only {available_seat} seat(s) available. Please choose from updated availability.")
            else:
                messages.warning(request, "Please login to book a train.")
                return redirect('login')
        else:
            messages.warning(request, 'Find a train first!')
            return redirect('home')



      
from django.shortcuts import render, get_object_or_404
from .models import Booking, ClassType

def confirm_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    fare_each = booking.class_type
    
    context = {
        'booking': booking,
        'user': request.user,
        'train': booking.train_name,
        'source': booking.source,
        'destination': booking.destination,
        'date': booking.travel_date,
        'departure': booking.departure_time,
        'arrival': booking.arrival_time,
        'tp': int(booking.passengers_adult) + int(booking.passengers_child),
        'pa': booking.passengers_adult,
        'pc': booking.passengers_child,
        'ctype': booking.class_type,
        'fare_each': fare_each,
        'adult_fare': fare_each.effective_adult_price if fare_each else None,
        'child_fare': fare_each.effective_child_price if fare_each else None,
        'selected_seats': booking.selected_seats,
        'total_fare': booking.total_fare
    }
    return render(request, 'booking.html', context)

# booking history page view

class BookingHistory(View):
    def get(self, request):
        _cleanup_expired_unpaid_bookings()
        user=request.user
        if user.is_authenticated:
            bookings = Booking.objects.filter(user=user).order_by('-id')

            current_time = timezone.now().astimezone(dt_timezone.utc)


            
            return render(request, 'booking_history.html', {'bookings':bookings, 'current_date':current_time})
        else:
            return redirect('login')

# booking detail page view

class BookingDetails(View):
    def get(self, request, pk):
        if not request.user.is_authenticated:
            return redirect('login')

        booking = Booking.objects.filter(id=pk).first()
        if not booking or booking.user != request.user:
            messages.warning(request, "Invalid booking id!")
            return redirect('booking_history')

        booking_detail = BookingDetail.objects.filter(booking=booking).order_by('-id').first()
        billing = BillingInfo.objects.filter(booking=booking).order_by('-id').first()
        payment = Payment.objects.filter(booking=booking).order_by('-id').first()
        passenger_total = (booking.passengers_adult or 0) + (booking.passengers_child or 0)
        fare_each = booking.class_type.price if booking.class_type else None
        adult_fare = booking.class_type.effective_adult_price if booking.class_type else None
        child_fare = booking.class_type.effective_child_price if booking.class_type else None

        context = {
            'booking': booking,
            'booking_detail': booking_detail,
            'billing': billing,
            'payment': payment,
            'passenger_total': passenger_total,
            'fare_each': fare_each,
            'adult_fare': adult_fare,
            'child_fare': child_fare,
        }
        return render(request, 'booking_detail.html', context)


# # ticket page view


class Tickets(View):
    def get(self, request, pk):
        if not request.user.is_authenticated:
            messages.warning(request, "Please login to view tickets.")
            return redirect('login')

        try:
            booking = get_object_or_404(Booking, id=pk, user=request.user)
            tickets = Ticket.objects.filter(booking=booking)
            payment = Payment.objects.filter(booking=booking).order_by('-id').first()
            if booking.status != "Canceled" and payment and (payment.status or "").strip().lower() == "paid":
                _mark_booking_paid(booking, payment_method=(payment.pay_method or "MPesa"))
            if booking.status != "Accepted" or not payment or (payment.status or "").strip().lower() != "paid":
                messages.warning(request, "Ticket is available only after successful payment.")
                return redirect('booking_detail', pk=booking.id)
            billing = BillingInfo.objects.filter(booking=booking).order_by('-id').first()
            booking_detail = BookingDetail.objects.filter(booking=booking).order_by('-id').first()
            print_param = request.GET.get('print', False)

            passenger_total = (booking.passengers_adult or 0) + (booking.passengers_child or 0)
            generate_ticket_pdf(booking)
            ticket_file_url = request.build_absolute_uri(f'/media/tickets/ticket_{booking.id}.pdf')
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
            class_type_value = booking.class_type.name if booking.class_type else ''
            pay_method_value = payment.pay_method if payment else 'MPesa'
            trxid_value = payment.trxid if payment else 'Pending'
            pay_status_value = payment.status if payment else 'Paid'
            booking_status_value = "Booked" if booking.status == "Accepted" else (booking.status or "Pending")
            selected_seats_value = booking.selected_seats or "-"

            context = {
                'booking': booking,
                'tickets': tickets,
                'payment': payment,
                'billing': billing,
                'booking_detail': booking_detail,
                'ticket_file_url': ticket_file_url,
                'passenger_total': passenger_total,
                'passenger_name': passenger_name,
                'email_value': email_value,
                'phone_value': phone_value,
                'class_type_value': class_type_value,
                'pay_method_value': pay_method_value,
                'trxid_value': trxid_value,
                'pay_status_value': pay_status_value,
                'booking_status_value': booking_status_value,
                'selected_seats_value': selected_seats_value,
                'print': print_param,
            }
            return render(request, 'ticket.html', context)
        except Booking.DoesNotExist:
            messages.warning(request, 'Booking not found or not authorized!')
            return redirect('booking_history')


# cancel booking view

class CancelBooking(View):
    def post(self, request):
        if not request.user.is_authenticated:
            messages.warning(request, 'Please login first.')
            return redirect('login')

        booking_id = request.POST.get('booking_id')
        if not booking_id:
            messages.warning(request, 'Missing booking id.')
            return redirect('booking_history')

        booking = Booking.objects.filter(id=booking_id, user=request.user).first()
        if not booking:
            messages.warning(request, 'Invalid booking id!')
            return redirect('booking_history')

        seat_tuples = list(
            SeatAllocation.objects.filter(booking_id=booking.id).values_list(
                "train_id", "class_type_id", "travel_date"
            )
        )

        # Free reserved seats but preserve booking history as canceled.
        SeatAllocation.objects.filter(booking_id=booking.id).delete()
        booking.status = "Canceled"
        booking.save(update_fields=["status", "updated_at"])

        for train_id, class_type_id, travel_date in seat_tuples:
            if train_id and class_type_id and travel_date:
                _bump_availability_version(train_id, class_type_id, travel_date)

        messages.success(request, 'Your booking canceled successfully')
        return redirect('booking_history')


# signup for user

def signup(request):
    user = request.user
    if user.is_authenticated:
        return redirect('home')
    else:
        if request.method=="POST":
            first_name = request.POST['first_name'].strip()
            last_name = request.POST['last_name'].strip()
            username = request.POST['username'].strip()
            email = request.POST['email'].strip()
            phone = request.POST['phone'].strip()
            password1 = request.POST['password1']
            password2 = request.POST['password2']

            if password1 != password2:
                messages.warning(request,"Password didn't matched")
                return redirect('signup')
        
            elif username == '':
                messages.warning(request,"Please enter a username")
                return redirect('signup')

            elif first_name == '':
                messages.warning(request,"Please enter first name")
                return redirect('signup')

            elif last_name == '':
                messages.warning(request,"Please enter last name")
                return redirect('signup')

            elif email == '':
                messages.warning(request,"Please enter email address")
                return redirect('signup')

            elif phone == '':
                messages.warning(request,"Please enter phone number")
                return redirect('signup')

            elif password1 == '':
                messages.warning(request,"Please enter password")
                return redirect('signup')

            elif password2 == '':
                messages.warning(request,"Please enter confirm password")
                return redirect('signup')

            if CustomUser.objects.filter(username=username).exists():
                messages.warning(request, "Username is not available")
                return redirect('signup')

            if CustomUser.objects.filter(email__iexact=email).exists():
                messages.warning(request, "Email is already registered")
                return redirect('signup')

            if CustomUser.objects.filter(phone=phone).exists():
                messages.warning(request, "Phone number is already registered")
                return redirect('signup')

            try:
                new_user = CustomUser.objects.create_user(
                    first_name=first_name,
                    last_name=last_name,
                    username=username,
                    email=email,
                    phone=phone,
                    password=password1
                )
                new_user.is_superuser = False
                new_user.is_staff = False
                new_user.save()
            except IntegrityError:
                messages.warning(request, "Account already exists with the provided credentials")
                return redirect('signup')

            messages.success(request,"Registration Successfull")
            return redirect("login")
        return render(request, 'signup.html')


# login for admin and user

def user_login(request):
    check = request.user
    if check.is_authenticated:
        return redirect('home')
    else:
            
        if request.method == 'POST':
            username = request.POST['username']
            password = request.POST['password']

            user = authenticate(username=username,password=password)
            
            if user is not None:
                login(request,user)
                messages.success(request,"successful logged in")
                return redirect('home')
            else:
                messages.warning(request,"Incorrect username or password")
                return redirect('login')

    response = render(request, 'login.html')
    return HttpResponse(response)


# contact page view

class Contact(View):
    def get(self, request):
        contact = ContactNumber.objects.all()
        return render(request, 'contact.html', {'contact': contact})

    def post(self, request):
        name = request.POST['name']
        email = request.POST['email']
        message = request.POST['message']

        if name == '' or email == '' or message == '':
            messages.warning(request, 'Please fillup all the fields to send message!')
            return redirect('contact')
        
        else:
            form = ContactForm(name=name, email=email, message=message)
            form.save()
            messages.success(request, 'You have successfully sent the message!')  
            return redirect('contact')


# feedback page view

class Feedbacks(View):
    def get(self, request):
        feedback = Feedback.objects.all().order_by('-id')
        return render(request, 'feedback.html', {'feedback': feedback})

    def post(self, request):
        user = request.user
        if user.is_authenticated:
            comment = request.POST['feedback']

            if comment == '':
                messages.warning(request, "please write something first and then submit feedback.")
                return redirect('feedback')
            
            else:
                feedback = Feedback(name=user.first_name + ' ' + user.last_name, feedback=comment)
                feedback.save()
                messages.success(request, 'Thanks for your feedback!')
                return redirect('feedback')

        else:
            messages.warning(request, "Please login first to post feedback.")
            return redirect('feedback')


# verify ticket page view

class VerifyTicket(View):
    def get(self, request):
        trains = Train.objects.all()
        context = {'train': trains}

        if request.GET:
            query_train = (request.GET.get('train') or '').strip()
            query_date = (request.GET.get('date') or '').strip()
            query_tid = (request.GET.get('tid') or '').strip()

            verified = False
            ticket = None
            booking = None

            # Primary check: explicit Ticket record by id.
            if query_tid:
                ticket = Ticket.objects.filter(
                    id=query_tid
                ).first()
                if ticket:
                    verified = True
                    query_train = ticket.train_name
                    query_date = str(ticket.travel_date)

            # Fallback check: booking id used as ticket id (common in this app flow)
            if not verified and query_tid.isdigit():
                booking = Booking.objects.filter(id=int(query_tid)).first()
                if booking:
                    has_payment = Payment.objects.filter(booking=booking).exists()
                    verified = has_payment
                    query_train = booking.train_name or query_train
                    query_date = str(booking.travel_date) if booking.travel_date else query_date

            context.update(
                {
                    'ticket': ticket,
                    'verified': verified,
                    'query_train': query_train,
                    'query_date': query_date,
                    'query_tid': query_tid,
                }
            )

        return render(request, 'verify_ticket.html', context)
from django.shortcuts import render
from app.models import Booking, BookingDetail, MpesaTransaction

def payment_success(request):
    booking_id = request.GET.get('booking_id')
    payment_code = request.GET.get('payment_code')  # This is your trx_id

    if not booking_id or not payment_code:
        return render(request, 'error.html', {'message': 'Missing booking ID or transaction code.'})

    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        return render(request, 'error.html', {'message': 'Booking not found.'})

    # ✅ Verify that the transaction exists and was successful (result_code='0')
    try:
        transaction = MpesaTransaction.objects.get(
            booking=booking,
            trx_id=payment_code,
            result_code='0'  # success
        )
    except MpesaTransaction.DoesNotExist:
        return render(request, 'error.html', {'message': 'Transaction not found. Check trx_id.'})

    # Fetch booking details
    booking_detail = getattr(booking, 'bookingdetail', None)

    return render(request, 'ticket.html', {
        'booking': booking,
        'booking_detail': booking_detail,
        'payment_code': payment_code
    })

from django.views import View
from django.shortcuts import render, redirect
from .forms import ProfileForm

class Profile(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('login')
        form = ProfileForm(instance=request.user)
        return render(request, 'profile.html', {'form': form})

    def post(self, request):
        if not request.user.is_authenticated:
            return redirect('login')
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect('profile')  # Or show a success message
        return render(request, 'profile.html', {'form': form})
   

def logout(request):
    if request.user.is_authenticated:
        auth_logout(request)
        print('User logged out')
    else:
        print('User was not logged in')
    
    return render(request, 'logout.html')
           

class CustomPasswordResetView(SuccessMessageMixin, PasswordResetView):
    template_name = 'forgot_password.html'
    email_template_name = 'reset_email.html'
    subject_template_name = 'reset_subject.txt'
    success_url = reverse_lazy('password_reset_done')
    success_message = "We've emailed you instructions for setting your password."
 
     
     

def get_access_token():
    consumer_key = settings.MPESA_CONSUMER_KEY
    consumer_secret = settings.MPESA_CONSUMER_SECRET
    api_URL = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    response = requests.get(api_URL, auth=(consumer_key, consumer_secret))
    access_token = response.json().get('access_token')
    return access_token


def query_stk_push_status(checkout_request_id):
    """
    Ask Daraja STK Query API for the current transaction result.
    Returns a dict with keys:
    - ok: bool (query request accepted)
    - status_known: bool (ResultCode present)
    - result_code: str|None
    - result_desc: str
    - rate_limited: bool
    """
    try:
        access_token = get_access_token()
        if not access_token:
            return {
                "ok": False,
                "status_known": False,
                "result_code": None,
                "result_desc": "Missing access token",
                "rate_limited": False,
            }

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode(
            f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{timestamp}".encode()
        ).decode("utf-8")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "BusinessShortCode": settings.MPESA_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }

        res = requests.post(
            "https://sandbox.safaricom.co.ke/mpesa/stkpushquery/v1/query",
            headers=headers,
            json=payload,
            timeout=15,
        )
        raw_text = (res.text or "").strip()
        try:
            data = res.json() if raw_text else {}
        except ValueError:
            print(
                f"[STK QUERY NON-JSON] checkout={checkout_request_id} "
                f"status={res.status_code} body={raw_text[:240]}"
            )
            return {
                "ok": False,
                "status_known": False,
                "result_code": None,
                "result_desc": "Invalid STK Query response from MPesa gateway",
                "rate_limited": bool(res.status_code == 429),
            }
        print(f"[STK QUERY RESPONSE] checkout={checkout_request_id} data={data}")

        detail = data.get("detail") or {}
        error_code = (
            detail.get("errorcode")
            or data.get("errorCode")
            or data.get("errorcode")
            or ""
        )
        is_rate_limited = (
            str(res.status_code) == "429"
            or "SpikeArrestViolation" in str(error_code)
            or "Spike arrest violation" in str(data.get("fault", {}).get("faultstring", ""))
        )
        if is_rate_limited:
            return {
                "ok": False,
                "status_known": False,
                "result_code": None,
                "result_desc": "Daraja rate limit reached. Backing off before next query.",
                "rate_limited": True,
            }

        if str(data.get("ResponseCode")) != "0":
            return {
                "ok": False,
                "status_known": False,
                "result_code": None,
                "result_desc": data.get("errorMessage") or data.get("ResponseDescription") or "STK Query failed",
                "rate_limited": False,
            }

        result_code = data.get("ResultCode")
        result_desc = data.get("ResultDesc") or data.get("ResponseDescription") or ""
        return {
            "ok": True,
            "status_known": result_code is not None,
            "result_code": str(result_code) if result_code is not None else None,
            "result_desc": result_desc,
            "rate_limited": False,
        }
    except Exception as e:
        print(f"[STK QUERY ERROR] checkout={checkout_request_id} err={e}")
        return {
            "ok": False,
            "status_known": False,
            "result_code": None,
            "result_desc": str(e),
            "rate_limited": False,
        }


def lipa_na_mpesa_online(phone_number, amount):
    try:
        access_token = get_access_token()
        api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')  # ✅ CORRECT

        password = base64.b64encode(
            (settings.MPESA_SHORTCODE + settings.MPESA_PASSKEY + timestamp).encode()
        ).decode()

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "BusinessShortCode": settings.MPESA_SHORTCODE,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": phone_number,
            "PartyB": settings.MPESA_SHORTCODE,
            "PhoneNumber": phone_number,
            "CallBackURL": settings.MPESA_CALLBACK_URL,
            "AccountReference": "Northern Express",
            "TransactionDesc": "Payment for Train Booking"
        }

        print("[MPESA REQUEST]:", json.dumps(payload, indent=2))
        response = requests.post(api_url, json=payload, headers=headers)

        try:
            return response.json()
        except ValueError:
            print("[MPESA ERROR]: Non-JSON response:", response.text)
            return {"error": "Invalid MPESA response", "raw": response.text}

    except Exception as e:
        print("[MPESA INIT ERROR]:", e)
        return {"error": str(e)}



# from app.models import Booking  # or whatever your model is



# from django.shortcuts import render, redirect
# from django.contrib import messages

# @csrf_exempt

# @login_required


# def process_payment(request):
#     booking_id = request.POST.get('booking_id')
#     payment_type = request.POST.get('ptype')
#     payment_code = request.POST.get('payment_code')

#     print(f"[PROCESS PAYMENT] Booking ID: {booking_id}, Payment Type: {payment_type}, Payment Code: {payment_code}")

#     if not booking_id:
#         return JsonResponse({'message': 'Booking ID is missing.'}, status=400)

#     if not payment_code:
#         return JsonResponse({'message': 'Payment code is required for confirmation.'}, status=400)

#     if payment_type != 'rocket':
#         return JsonResponse({'message': 'Unsupported payment type.'}, status=400)

#     try:
#         booking = Booking.objects.get(id=booking_id)
#     except Booking.DoesNotExist:
#         return JsonResponse({'message': 'Booking not found.'}, status=404)

#     if booking.user != request.user:
#         return JsonResponse({'message': 'This booking does not belong to you.'}, status=403)

#     print(f"[DEBUG] Booking validated for user {request.user}")

#     try:
#         transaction = MpesaTransaction.objects.get(booking=booking, trx_id=payment_code)
#     except MpesaTransaction.DoesNotExist:
#         return JsonResponse({'message': 'Transaction not found. Check the transaction ID.'}, status=404)

#     print(f"[DEBUG] Payment Match Found: {transaction}")

#     # Create or update the payment record
#     payment, created = Payment.objects.update_or_create(
#         booking=booking,
#         defaults={
#             'trxid': payment_code,
#             'user': request.user
#         }
#     )

#     # Update user phone number if needed
#     if transaction.phone_number:
#         if not getattr(booking.user, 'phone', None):
#             booking.user.phone = transaction.phone_number
#             booking.user.save()
#         transaction.save()

#     receipt_data = {
#         'transaction_id': transaction.trx_id,
#         'amount': transaction.amount,
#         'phone': transaction.phone_number,
#         'date': now().strftime('%Y-%m-%d %H:%M:%S')
#     }

#     return JsonResponse({
#         'message': 'MPesa payment confirmed successfully.',
#         'booking_id': booking.id,
#         'receipt': receipt_data
#     }, status=200)

from django.shortcuts import get_object_or_404
from django.http import JsonResponse, FileResponse, HttpResponse
from django.utils.timezone import now
from django.conf import settings
from reportlab.pdfgen import canvas
import os
from .models import Booking, MpesaTransaction, Payment
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required

# Utility function to generate ticket PDF
def generate_ticket_pdf(booking):
    from .utils import generate_ticket_pdf as generate_ticket_pdf_util
    return generate_ticket_pdf_util(booking)


def _mark_booking_paid(booking, payment_method="MPesa"):
    if booking.status == "Canceled":
        return
    changed_fields = []
    if booking.status != "Accepted":
        booking.status = "Accepted"
        changed_fields.append("status")
    if payment_method and booking.payment_method != payment_method:
        booking.payment_method = payment_method
        changed_fields.append("payment_method")
    if changed_fields:
        booking.save(update_fields=changed_fields + ["updated_at"])
    
from django.shortcuts import get_object_or_404, redirect
from django.http import JsonResponse, FileResponse
from django.views.decorators.csrf import csrf_exempt
import os
from .models import Booking, MpesaTransaction, Payment
from django.conf import settings

@csrf_exempt
def process_payment(request):
    if request.method != "POST":
        return JsonResponse({'message': 'Invalid request method.'}, status=405)

    booking_id = request.POST.get('booking_id')
    payment_type = request.POST.get('ptype')
    payment_code = (request.POST.get('payment_code') or '').strip().upper()
    print(f"[PROCESS PAYMENT] booking_id={booking_id}, ptype={payment_type}, payment_code={payment_code}")

    if not booking_id or not payment_code or not payment_type:
        return JsonResponse({'message': 'Missing booking_id, ptype, or payment_code.'}, status=400)

    if payment_type != 'rocket':
        return JsonResponse({'message': 'Unsupported payment type.'}, status=400)

    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        return JsonResponse({'message': 'Booking not found.'}, status=404)

    if booking.user != request.user:
        return JsonResponse({'message': 'This booking does not belong to you.'}, status=403)

    if booking.status == 'Canceled':
        return JsonResponse({'message': 'This booking is canceled and cannot be paid.'}, status=400)

    transaction = MpesaTransaction.objects.filter(
        booking=booking,
        trx_id__iexact=payment_code
    ).order_by('-id').first()
    if not transaction:
        pending_txn = MpesaTransaction.objects.filter(
            booking=booking
        ).order_by('-id').first()
        if pending_txn and (pending_txn.result_code in (None, '', '-1') or not pending_txn.trx_id):
            return JsonResponse(
                {
                    'message': 'Payment is still pending MPesa callback. Wait a few seconds and try again.'
                },
                status=400
            )
        if pending_txn and pending_txn.result_code not in (None, '', '-1', '0'):
            return JsonResponse(
                {
                    'message': f"MPesa transaction failed: {pending_txn.result_desc or 'Unknown failure'}"
                },
                status=400
            )
        return JsonResponse(
            {
                'message': 'No matching MPesa transaction found for this booking and confirmation code.'
            },
            status=400
        )

    # Create or update payment
    Payment.objects.update_or_create(
        booking=booking,
        user=request.user,
        defaults={
            'pay_amount': str(transaction.amount) if transaction.amount is not None else str(booking.total_fare or ''),
            'pay_method': 'MPesa',
            'phone': str(transaction.phone_number or request.POST.get('phone', '')),
            'trxid': payment_code,
            'status': 'Paid',
        }
    )

    _mark_booking_paid(booking, payment_method="MPesa")

    # Update phone if missing
    if transaction.phone_number and not getattr(booking.user, 'phone', None):
        booking.user.phone = transaction.phone_number
        booking.user.save()

    # Generate ticket PDF
    generate_ticket_pdf(booking)

    return JsonResponse(
        {
            'message': 'MPesa payment confirmed successfully.',
            'booking_id': booking.id
        },
        status=200
    )


@login_required
def mpesa_status(request):
    booking_id = request.GET.get('booking_id')
    if not booking_id:
        return JsonResponse({'message': 'Missing booking_id.'}, status=400)

    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        return JsonResponse({'message': 'Booking not found.'}, status=404)

    if booking.user != request.user:
        return JsonResponse({'message': 'This booking does not belong to you.'}, status=403)

    if booking.status == 'Canceled':
        return JsonResponse({'status': 'canceled', 'message': 'This booking was canceled.'}, status=200)

    txn = MpesaTransaction.objects.filter(booking=booking).order_by('-id').first()
    if not txn:
        return JsonResponse({'status': 'pending', 'message': 'No MPesa transaction yet.'}, status=200)

    if str(txn.result_code) == '0':
        Payment.objects.update_or_create(
            booking=booking,
            user=booking.user,
            defaults={
                'trxid': txn.trx_id or txn.checkout_request_id,
                'pay_amount': str(txn.amount if txn.amount is not None else booking.total_fare or ''),
                'pay_method': 'MPesa',
                'phone': str(txn.phone_number or ''),
                'status': 'Paid',
            }
        )
        _mark_booking_paid(booking, payment_method="MPesa")
        return JsonResponse(
            {
                'status': 'success',
                'booking_id': booking.id,
                'trx_id': txn.trx_id,
                'result_desc': txn.result_desc,
                'checkout_request_id': txn.checkout_request_id,
            },
            status=200
        )

    timeout_seconds = getattr(settings, 'MPESA_CALLBACK_TIMEOUT_SECONDS', 180)
    min_query_interval_seconds = max(
        int(getattr(settings, 'MPESA_STK_QUERY_MIN_INTERVAL_SECONDS', 15)),
        1,
    )
    rate_limit_backoff_seconds = max(
        int(getattr(settings, 'MPESA_STK_QUERY_RATE_LIMIT_BACKOFF_SECONDS', 30)),
        min_query_interval_seconds,
    )
    elapsed_seconds = int((timezone.now() - txn.created_at).total_seconds()) if txn.created_at else 0

    if txn.result_code in (None, '', '-1'):
        # Callback can be delayed/missed; query Daraja directly as fallback.
        # Throttle query attempts per checkout ID to avoid hammering API on each poll.
        query_lock_key = f"stk_query_lock:{txn.checkout_request_id}"
        next_poll_seconds = min_query_interval_seconds
        pending_message = 'Waiting for MPesa callback.'
        if txn.checkout_request_id and cache.add(query_lock_key, "1", timeout=min_query_interval_seconds):
            query_result = query_stk_push_status(txn.checkout_request_id)
            if query_result.get("status_known"):
                txn.result_code = query_result.get("result_code")
                txn.result_desc = query_result.get("result_desc")
                txn.save(update_fields=["result_code", "result_desc"])

                if txn.result_code == '0':
                    Payment.objects.update_or_create(
                        booking=booking,
                        user=booking.user,
                        defaults={
                            'trxid': txn.trx_id or txn.checkout_request_id,
                            'pay_amount': str(txn.amount if txn.amount is not None else booking.total_fare or ''),
                            'pay_method': 'MPesa',
                            'phone': str(txn.phone_number or ''),
                            'status': 'Paid',
                        }
                    )
                    _mark_booking_paid(booking, payment_method="MPesa")
                    generate_ticket_pdf(booking)
                    return JsonResponse(
                        {
                            'status': 'success',
                            'booking_id': booking.id,
                            'trx_id': txn.trx_id or txn.checkout_request_id,
                            'result_desc': txn.result_desc,
                            'checkout_request_id': txn.checkout_request_id,
                        },
                        status=200
                    )

                if txn.result_code not in (None, '', '-1'):
                    return JsonResponse(
                        {
                            'status': 'failed',
                            'message': txn.result_desc or 'MPesa transaction failed.',
                            'elapsed_seconds': elapsed_seconds,
                            'timeout_seconds': timeout_seconds,
                            'result_code': txn.result_code,
                            'checkout_request_id': txn.checkout_request_id,
                        },
                        status=200
                    )
            elif query_result.get("rate_limited"):
                next_poll_seconds = rate_limit_backoff_seconds
                pending_message = query_result.get("result_desc") or (
                    'MPesa gateway rate-limited status checks. Retrying automatically.'
                )
                cache.set(query_lock_key, "1", timeout=next_poll_seconds)

        if elapsed_seconds >= timeout_seconds:
            return JsonResponse(
                {
                    'status': 'expired',
                    'message': 'No MPesa callback received in time. Please retry payment.',
                    'elapsed_seconds': elapsed_seconds,
                    'timeout_seconds': timeout_seconds,
                },
                status=200
            )
        return JsonResponse(
            {
                'status': 'pending',
                'message': pending_message,
                'elapsed_seconds': elapsed_seconds,
                'timeout_seconds': timeout_seconds,
                'next_poll_seconds': next_poll_seconds,
                'checkout_request_id': txn.checkout_request_id,
            },
            status=200
        )

    return JsonResponse(
        {
            'status': 'failed',
            'message': txn.result_desc or 'MPesa transaction failed.',
            'elapsed_seconds': elapsed_seconds,
            'timeout_seconds': timeout_seconds,
            'result_code': txn.result_code,
            'checkout_request_id': txn.checkout_request_id,
        },
        status=200
    )



from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponseBadRequest
from django.conf import settings
from django.utils import timezone
from django.urls import reverse
from datetime import datetime
import base64               
import requests
import json
from urllib.parse import urlparse


def _is_valid_daraja_callback_url(url):
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or parsed.scheme.lower() != "https":
        return False
    if not parsed.netloc:
        return False
    if parsed.path != "/mpesa_callback/":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0"}
    if host in blocked_hosts:
        return False
    if host.startswith("192.168.") or host.startswith("10.") or host.startswith("172.16."):
        return False
    if "your-public-domain" in url:
        return False
    return True


def _resolve_callback_url(request):
    configured = (getattr(settings, "MPESA_CALLBACK_URL", "") or "").strip()
    if _is_valid_daraja_callback_url(configured):
        return configured

    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    scheme = forwarded_proto or ("https" if request.is_secure() else "http")
    forwarded_host = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    host = forwarded_host or request.get_host()
    dynamic = f"{scheme}://{host}{reverse('mpesa_callback')}"
    if _is_valid_daraja_callback_url(dynamic):
        return dynamic

    # If ngrok is running locally, auto-discover its public HTTPS URL.
    try:
        tunnels_res = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=1.5)
        tunnels = tunnels_res.json().get("tunnels", [])
        for tunnel in tunnels:
            public_url = (tunnel.get("public_url") or "").strip()
            if public_url.startswith("https://"):
                ngrok_callback = f"{public_url.rstrip('/')}{reverse('mpesa_callback')}"
                if _is_valid_daraja_callback_url(ngrok_callback):
                    return ngrok_callback
    except Exception:
        pass

    return dynamic


def _is_missing_or_placeholder_secret(value):
    text = (value or "").strip().lower()
    return (not text) or (text == "change-me") or ("your-" in text)


@csrf_exempt
def stk_push(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            raw_phone = data.get('phone')

            if not raw_phone:
                return JsonResponse({'status': 'error', 'message': 'Phone number is required'}, status=400)

            phone = raw_phone.strip().replace(' ', '').replace('+', '')
            if phone.startswith('0'):
                phone = '254' + phone[1:]
            elif phone.startswith('7'):
                phone = '254' + phone
            elif not phone.startswith('254'):
                return JsonResponse({'status': 'error', 'message': 'Phone number must start with 07, 7 or 254'}, status=400)

            if not phone.isdigit() or len(phone) != 12:
                return JsonResponse({'status': 'error', 'message': 'Invalid phone number format'}, status=400)

            amount = data.get('amount')
            booking_id = data.get('booking_id')

            if not phone or not amount or not booking_id:
                return JsonResponse({'status': 'error', 'message': 'Missing phone, amount, or booking ID'}, status=400)

            try:
                booking = Booking.objects.get(id=booking_id)
            except Booking.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Invalid booking ID'}, status=404)

            existing_payment = Payment.objects.filter(
                booking=booking,
                status__iexact='Paid'
            ).order_by('-id').first()
            if existing_payment:
                return JsonResponse(
                    {
                        'status': 'success',
                        'message': 'Booking is already paid.',
                        'booking_id': booking.id,
                        'trx_id': existing_payment.trxid,
                        'already_paid': True,
                    },
                    status=200
                )

            existing_pending_txn = MpesaTransaction.objects.filter(booking=booking).filter(
                Q(result_code__isnull=True) | Q(result_code='') | Q(result_code='-1')
            ).order_by('-id').first()
            if existing_pending_txn:
                return JsonResponse(
                    {
                        'status': 'pending',
                        'message': 'A payment request is already pending confirmation.',
                        'checkout_request_id': existing_pending_txn.checkout_request_id,
                    },
                    status=200
                )

            consumer_key = settings.MPESA_CONSUMER_KEY
            consumer_secret = settings.MPESA_CONSUMER_SECRET
            shortcode = settings.MPESA_SHORTCODE
            passkey = settings.MPESA_PASSKEY

            if (
                _is_missing_or_placeholder_secret(consumer_key)
                or _is_missing_or_placeholder_secret(consumer_secret)
                or _is_missing_or_placeholder_secret(passkey)
            ):
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': (
                            'MPesa credentials are not configured. '
                            'Set MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, and MPESA_PASSKEY in .env.'
                        ),
                    },
                    status=400
                )

            callback_url = _resolve_callback_url(request)
            if not _is_valid_daraja_callback_url(callback_url):
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': (
                            'Invalid callback URL. Use a public HTTPS domain ending with /mpesa_callback/.'
                        ),
                        'callback_url': callback_url,
                        'configured_callback_url': (settings.MPESA_CALLBACK_URL or "").strip(),
                    },
                    status=400
                )
            print(f"[STK PUSH] Callback URL: {callback_url}")

            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            password = base64.b64encode(f'{shortcode}{passkey}{timestamp}'.encode()).decode('utf-8')

            # Get access token
            token_url = 'https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials'
            try:
                r = requests.get(token_url, auth=(consumer_key, consumer_secret), timeout=15)
            except requests.RequestException as exc:
                print(f"[STK PUSH ERROR]: Access token request failed: {exc}")
                return JsonResponse(
                    {'status': 'error', 'message': 'Failed to reach MPesa auth server. Check internet connection.'},
                    status=502
                )

            try:
                access_token = r.json().get('access_token')
            except ValueError:
                print("[STK PUSH ERROR]: Could not parse access token response.")
                print(f"Access token status: {r.status_code}")
                print(f"Access token raw response: {r.text}")
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': 'Invalid response while fetching access token.',
                        'http_status': r.status_code,
                    },
                    status=502
                )

            if not access_token:
                print(f"[STK PUSH ERROR]: Access token missing. Status={r.status_code}, Body={r.text}")
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': 'Access token not found. Check MPesa credentials.',
                        'http_status': r.status_code,
                    },
                    status=502
                )

            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }

            payload = {
                "BusinessShortCode": shortcode,
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": int(float(amount)),
                "PartyA": phone,
                "PartyB": shortcode,
                "PhoneNumber": phone,
                "CallBackURL": callback_url,
                "AccountReference": f"Booking{booking_id}",
                "TransactionDesc": "Train Ticket Payment"
            }

            res = requests.post(
                "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest",
                headers=headers,
                json=payload
            )

            try:
                response_data = res.json()
            except json.JSONDecodeError:
                print("[STK PUSH ERROR]: Invalid JSON from STK push request.")
                print(f"Raw response: {res.text}")
                return JsonResponse({'status': 'error', 'message': 'Invalid response from MPesa STK Push API.'}, status=500)

            print("[STK PUSH RESPONSE]", response_data)

            if response_data.get("ResponseCode") == "0":
                merchant_request_id = response_data.get("MerchantRequestID")
                checkout_request_id = response_data.get("CheckoutRequestID")

                MpesaTransaction.objects.create(
                    booking=booking,
                    phone_number=phone,
                    amount=amount,
                    merchant_request_id=merchant_request_id,
                    # Receipt code is only available in callback metadata (MpesaReceiptNumber).
                    trx_id=None,
                    checkout_request_id=checkout_request_id,
                    result_code='-1',
                    transaction_date=timezone.now()
                )

                return JsonResponse({
                    'status': 'success',
                    'message': 'STK Push initiated',
                    'response': response_data
                })

            return JsonResponse({
                'status': 'error',
                'message': response_data.get('errorMessage', 'Failed to initiate STK push')
            }, status=400)

        except Exception as e:
            print(f"[STK PUSH ERROR]: {str(e)}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return HttpResponseBadRequest("Invalid request method")


@csrf_exempt
def mpesa_callback(request):
    try:
        if request.method != "POST":
            return JsonResponse({"ResultCode": 1, "ResultDesc": "Invalid request method"}, status=405)

        data = json.loads(request.body.decode('utf-8'))
        body = data.get("Body", {}).get("stkCallback", {})
        merchant_request_id = body.get("MerchantRequestID")
        checkout_request_id = body.get("CheckoutRequestID")
        result_code = str(body.get("ResultCode"))
        result_desc = body.get("ResultDesc")

        trx_id = None
        amount = None
        phone = None

        # Extract transaction details safely
        for item in body.get("CallbackMetadata", {}).get("Item", []):
            name = item.get("Name")
            value = item.get("Value")
            if name == "MpesaReceiptNumber":
                trx_id = value
            elif name == "Amount":
                amount = value
            elif name == "PhoneNumber":
                phone = value

        print(f"[CALLBACK] CheckoutRequestID: {checkout_request_id}, TrxID: {trx_id}, ResultCode: {result_code}, Amount: {amount}, Phone: {phone}")

        # Fetch MpesaTransaction (prefer checkout ID; fallback to merchant ID for resilience).
        mpesa_transaction = None
        if checkout_request_id:
            mpesa_transaction = MpesaTransaction.objects.filter(
                checkout_request_id=checkout_request_id
            ).order_by("-id").first()
        if not mpesa_transaction and merchant_request_id:
            mpesa_transaction = MpesaTransaction.objects.filter(
                merchant_request_id=merchant_request_id
            ).order_by("-id").first()
        if not mpesa_transaction and checkout_request_id and merchant_request_id:
            mpesa_transaction = MpesaTransaction.objects.filter(
                checkout_request_id=checkout_request_id,
                merchant_request_id=merchant_request_id
            ).order_by("-id").first()
        if not mpesa_transaction:
            print(
                "[CALLBACK ERROR]: No MpesaTransaction found "
                f"(merchant_request_id={merchant_request_id}, checkout_request_id={checkout_request_id})"
            )
            # Always acknowledge callback to avoid provider retries.
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"}, status=200)

        # Update transaction record
        if trx_id:
            mpesa_transaction.trx_id = trx_id
        mpesa_transaction.result_code = result_code
        mpesa_transaction.result_desc = result_desc
        if amount is not None:
            mpesa_transaction.amount = amount
        if phone:
            mpesa_transaction.phone_number = phone
        mpesa_transaction.save()

        # Update user's phone if missing
        user = mpesa_transaction.booking.user

        if mpesa_transaction.booking.status == 'Canceled':
            return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"}, status=200)
        if user and hasattr(user, 'phone') and phone and (not user.phone or user.phone.strip() == ""):
            user.phone = phone
            user.save()

        # Create payment record and generate ticket only if success
        if result_code == '0':
            Payment.objects.update_or_create(
                booking=mpesa_transaction.booking,
                user=user,
                defaults={
                    'trxid': trx_id,
                    'pay_amount': str(amount) if amount is not None else str(mpesa_transaction.booking.total_fare or ''),
                    'pay_method': 'MPesa',
                    'phone': str(phone or ''),
                    'status': 'Paid',
                }
            )
            _mark_booking_paid(mpesa_transaction.booking, payment_method="MPesa")
            # Ensure ticket PDF is generated
            generate_ticket_pdf(mpesa_transaction.booking)
            print(f"[CALLBACK] Payment & Ticket saved for Booking ID: {mpesa_transaction.booking.id}")

        return JsonResponse({"ResultCode": 0, "ResultDesc": "Accepted"}, status=200)

    except Exception as e:
        print(f"[CALLBACK ERROR]: {e}")
        return JsonResponse({"ResultCode": 1, "ResultDesc": f"Failed: {str(e)}"}, status=500)


from django.views import View
from django.shortcuts import render, get_object_or_404
from django.conf import settings
import os
from .models import Booking
from .utils import generate_ticket_pdf  # Make sure this imports your PDF generator

class TicketView(View):
    def get(self, request, pk):
        # Get booking
        booking = get_object_or_404(Booking, id=pk)

        # Ensure tickets directory exists
        tickets_dir = os.path.join(settings.MEDIA_ROOT, 'tickets')
        os.makedirs(tickets_dir, exist_ok=True)

        # Path to PDF
        ticket_file = os.path.join(tickets_dir, f'ticket_{booking.id}.pdf')

        # Generate PDF if it doesn't exist
        if not os.path.exists(ticket_file):
            ticket_file = generate_ticket_pdf(booking)

        # Build URL for template
        ticket_file_url = request.build_absolute_uri(f'/media/tickets/ticket_{booking.id}.pdf')

        return render(request, 'ticket.html', {
            'booking': booking,
            'ticket_file_url': ticket_file_url,  # Pass the download link
            'print': request.GET.get('print', False),
        })
