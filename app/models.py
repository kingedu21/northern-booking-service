from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import User
from django.contrib.auth.models import User
# OR, if using a custom user model:
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from decimal import Decimal
# Create your models here.
from django.contrib.auth.models import AbstractUser
from django.db import models
class CustomUser(AbstractUser):
    first_name = models.CharField(max_length=150, blank=True, default='Unknown')  # ✅
    last_name = models.CharField(max_length=150, blank=True, default='Unknown')   # ✅
    email = models.EmailField(max_length=100, blank=True, unique=True, null=True)
    phone = models.CharField(verbose_name=_("Mobile phone"), max_length=14, blank=True, null=True, unique=True)
    photo = models.ImageField(verbose_name=_("Photo"), upload_to='users/', blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)


class Station(models.Model):
    name = models.CharField(max_length=100)
    place = models.CharField(max_length=100, blank=True, null=True)
    code = models.CharField(max_length=10, unique=True, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name}, {self.place}" if self.place else self.name

class ClassType(models.Model):
    name = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    adult_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    child_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return self.name

    @property
    def effective_adult_price(self):
        return self.adult_price if self.adult_price is not None else self.price

    @property
    def effective_child_price(self):
        return self.child_price if self.child_price is not None else self.price

    def calculate_total_fare(self, adults=0, children=0):
        adults = max(int(adults or 0), 0)
        children = max(int(children or 0), 0)
        return (Decimal(adults) * self.effective_adult_price) + (Decimal(children) * self.effective_child_price)





from django.db import models
from django.utils.translation import gettext_lazy as _

class Train(models.Model):
    name = models.CharField(
        verbose_name=_("Train Name"),
        max_length=255,
        null=True,
        blank=True
    )
    nos = models.PositiveIntegerField(
        verbose_name=_("Number of Seats"),
        null=True,
        blank=True,
        help_text=_("Total number of available seats on the train")
    )
    source = models.ForeignKey(
        'Station',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='departing_trains',
        verbose_name=_("Source Station")
    )
    destination = models.ForeignKey(
        'Station',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='arriving_trains',
        verbose_name=_("Destination Station")
    )
    departure_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_("Departure Time")
    )
    arrival_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_("Arrival Time")
    )
    class_type = models.ManyToManyField(
        'ClassType',
        blank=True,
        verbose_name=_("Class Types"),
        help_text=_("Select all available classes for this train")
    )
    capacity_group = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text=_("Optional shared seat-capacity group key for duplicate trip rows."),
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        null=True,
        blank=True
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        null=True,
        blank=True
    )

    def __str__(self):
        return self.name if self.name else "Unnamed Train"

    def seat_scope_key(self):
        group = (self.capacity_group or "").strip()
        if group:
            return f"group:{group.lower()}"
        return f"train:{self.id}"

    class Meta:
        verbose_name = _("Train")
        verbose_name_plural = _("Trains")
        ordering = ['name']


class TrainClassCapacity(models.Model):
    train = models.ForeignKey(
        'Train',
        on_delete=models.CASCADE,
        related_name='class_capacities'
    )
    class_type = models.ForeignKey(
        'ClassType',
        on_delete=models.CASCADE,
        related_name='train_capacities'
    )
    seat_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['train', 'class_type'],
                name='unique_train_class_capacity'
            )
        ]
        ordering = ['train', 'class_type']
        verbose_name = _("Train Class Capacity")
        verbose_name_plural = _("Train Class Capacities")

    def __str__(self):
        return f"{self.train} - {self.class_type}: {self.seat_count}"


class Booking(models.Model):
    status_choices = (
        ("Pending", "Pending"),
        ("Accepted", "Accepted"),
        ("Canceled", "Canceled"),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    booking_date = models.DateField(auto_now_add=True, null=True, blank=True)
    booking_time = models.TimeField(auto_now_add=True, null=True, blank=True)
    status = models.CharField(max_length=50, default='Pending', choices=status_choices, null=True, blank=True)
    train_name = models.CharField(max_length=100, null=True, blank=True)
    source = models.CharField(max_length=100, null=True, blank=True)
    destination = models.CharField(max_length=100, null=True, blank=True)
    departure_time = models.CharField(max_length=50, null=True, blank=True)
    arrival_time = models.CharField(max_length=50, null=True, blank=True)
    # class_type = models.CharField(max_length=50, null=True, blank=True)
    
    class_type = models.ForeignKey(ClassType, null=True, blank=True, on_delete=models.SET_NULL)

    total_fare = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    passengers_adult = models.IntegerField(null=True, blank=True)
    passengers_child = models.IntegerField(null=True, blank=True)
    payment_code = models.CharField(max_length=100, null=True, blank=True)
    payment_method = models.CharField(max_length=50, null=True, blank=True)
    travel_date = models.DateField(null=True, blank=True)
    travel_dt = models.DateTimeField(blank=True, null=True)
    selected_seats = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return f"Booking {self.id} by {self.user.username if self.user else 'Anonymous'}"


class Passenger(models.Model):
    class GenderChoices(models.TextChoices):
        MALE = "Male", "Male"
        FEMALE = "Female", "Female"
        OTHER = "Other", "Other"

    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="passengers",
    )
    full_name = models.CharField(max_length=120)
    gender = models.CharField(
        max_length=10,
        choices=GenderChoices.choices,
        default=GenderChoices.OTHER,
    )
    age = models.PositiveIntegerField(null=True, blank=True)
    seat_number = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "seat_number"],
                name="unique_booking_passenger_seat",
            )
        ]
        ordering = ["seat_number", "id"]

    def __str__(self):
        return f"{self.full_name} ({self.booking_id}) - Seat {self.seat_number}"





class BillingInfo(models.Model):
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return f"Billing for Booking {self.booking.id}"





class BookingDetail(models.Model):
    booking = models.OneToOneField(Booking, null=True, blank=True, on_delete=models.CASCADE)
    train = models.CharField(max_length=255, null=True, blank=True)
    source = models.CharField(max_length=255, null=True, blank=True)
    destination = models.CharField(max_length=255, null=True, blank=True)
    travel_date = models.DateField(null=True, blank=True)
    travel_time = models.TimeField(null=True, blank=True)
    nop = models.PositiveIntegerField(verbose_name=_("Number of Passengers"), null=True, blank=True)
    adult = models.PositiveIntegerField(null=True, blank=True)
    child = models.PositiveIntegerField(null=True, blank=True)
    class_type = models.CharField(max_length=255, null=True, blank=True)
    fpp = models.PositiveIntegerField(verbose_name=_("Fare Per Passenger"), null=True, blank=True)
    total_fare = models.PositiveIntegerField(null=True, blank=True)

    travel_dt = models.DateTimeField(blank=True, null=True)
    booking_dt = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)


class Payment(models.Model):
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    pay_amount = models.CharField(max_length=10)
    pay_method = models.CharField(max_length=50)
    phone = models.CharField(max_length=20)
    trxid = models.CharField(max_length=50)
    status = models.CharField(max_length=50, default='Paid', auto_created=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)


    def __str__(self):
        return f"Payment for Booking {self.booking.id}"



class Ticket(models.Model):
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE)
    passenger = models.ForeignKey('Passenger', on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')
    ticket_uid = models.CharField(max_length=32, unique=True, null=True, blank=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20)
    source = models.CharField(max_length=100)
    destination = models.CharField(max_length=100)
    departure = models.CharField(max_length=50)
    travel_date = models.DateField()
    train_name = models.CharField(max_length=100)
    class_type = models.CharField(max_length=50)
    seat_number = models.PositiveIntegerField(null=True, blank=True)
    fare = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return f"Ticket {self.ticket_uid or self.id} for Booking {self.booking.id}"





class MpesaTransaction(models.Model):
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, null=True)
    phone_number = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    checkout_request_id = models.CharField(max_length=100)
    merchant_request_id = models.CharField(max_length=100)
    trx_id = models.CharField(max_length=100, null=True, blank=True)
    result_code = models.CharField(max_length=10, null=True, blank=True)
    result_desc = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    transaction_date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"MPesa Transaction for Booking {self.booking.id if self.booking else 'None'}"



class ContactForm(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True) 

    def __str__(self):
        return f"Contact from {self.name}"


   


class ContactNumber(models.Model):
    phone = models.CharField(max_length=20)
    station = models.OneToOneField(Station, on_delete=models.CASCADE, null=True, blank=True)
    station_phone = models.CharField(verbose_name=_("Station Phone Number"), max_length=255, null=True, blank=True)
    emergency_center = models.CharField(verbose_name=_("Emergency Center Phone Number"), max_length=255, null=True, blank=True)
    help_desk = models.CharField(verbose_name=_("Help Desk Phone Number"), max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)


class Feedback(models.Model):
    name = models.CharField(max_length=100)
    feedback = models.TextField()

    def __str__(self):
        return f"Feedback from {self.name}"


class SeatAllocation(models.Model):
    train = models.ForeignKey('Train', on_delete=models.CASCADE, related_name='seat_allocations')
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='seat_allocations')
    class_type = models.ForeignKey('ClassType', on_delete=models.SET_NULL, null=True, blank=True, related_name='seat_allocations')
    travel_date = models.DateField()
    seat_number = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['train', 'class_type', 'travel_date', 'seat_number'],
                name='unique_train_class_date_seat'
            )
        ]
        ordering = ['travel_date', 'seat_number']

    def __str__(self):
        class_name = self.class_type.name if self.class_type else "Unassigned Class"
        return f"{self.train} {self.travel_date} {class_name} Seat {self.seat_number}"
