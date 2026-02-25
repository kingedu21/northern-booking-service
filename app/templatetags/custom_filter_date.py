from django import template
from datetime import datetime, date, time
from django.utils import timezone


register = template.Library()


# this filter has been created to to show cancel booking button if remaining date more than 1 day
@register.filter(name="date")
def date(travel_dt, current_date):
    try:
        result = travel_dt - current_date
        result = str(result)
        time = result.split()
        x = time[0]
        x = int(x)
        return x

    except Exception:
        return 0

    
# # this filter has been created to to show book button if current date is smaller than travel date
# @register.filter(name="book")
# def book(travel_dt, current_date):
#     try:
#         total = str(travel_dt) + ' ' + str(current_date)
#         pagla = datetime.strptime(total, '%Y-%m-%d %H:%M:%S.%fZ')
#         now = datetime.now(timezone.utc)
#         result = pagla - now
#         print(result)
#         result = str(result)
#         time = result.split()
        
#         nt = time[2].split(":")
#         ns = nt[0]
#         t = int(ns)
#         print(t)

#         d = time[0]
#         d = int(d)
        
#         if (d == 0 and t >= 1) or d > 0:
#             return True
#         else:
#             return False

#     except:
#         return redirect('home')


# this filter has been created to to show book button if current date is smaller than travel date
# if current train departure time left 1 or more than 1 hour than current time then, book button will be shown
@register.filter(name="add")
def add(travel_date, travel_time):
    travel_date = str(travel_date)
    travel_time = str(travel_time)
    travel_dt = travel_date + ' ' + travel_time
    return travel_dt

@register.filter(name="book")
def book(travel_date, travel_time):
    try:
        if isinstance(travel_date, str):
            travel_date = datetime.strptime(travel_date.strip(), "%Y-%m-%d").date()
        elif isinstance(travel_date, datetime):
            travel_date = travel_date.date()
        elif not isinstance(travel_date, date):
            return False

        if isinstance(travel_time, str):
            raw = travel_time.strip()
            parsed_time = None
            for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
                try:
                    parsed_time = datetime.strptime(raw, fmt).time()
                    break
                except ValueError:
                    continue
            if parsed_time is None:
                return False
            travel_time = parsed_time
        elif isinstance(travel_time, datetime):
            travel_time = travel_time.time()
        elif not isinstance(travel_time, time):
            return False

        travel_dt = datetime.combine(travel_date, travel_time)
        travel_dt = timezone.make_aware(travel_dt, timezone.get_current_timezone())
        current_dt = timezone.localtime()

        return (travel_dt - current_dt).total_seconds() >= 3600
    except Exception:
        return False

    # return travel_dt

    # except:
    #     return redirect('home')
