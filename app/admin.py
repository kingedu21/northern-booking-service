from django.contrib import admin

from .models import (
    BillingInfo,
    Booking,
    BookingDetail,
    ClassType,
    ContactForm,
    ContactNumber,
    CustomUser,
    Feedback,
    MpesaTransaction,
    Payment,
    Passenger,
    SeatAllocation,
    Station,
    Ticket,
    Train,
    TrainClassCapacity,
)


def all_fields(model):
    return [field.name for field in model._meta.fields]


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']


@admin.register(ClassType)
class ClassTypeAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'price', 'adult_price', 'child_price']


@admin.register(Train)
class TrainAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'capacity_group',
        'source',
        'destination',
        'departure_time',
        'arrival_time',
        'get_class_types',
    )
    list_filter = ('source', 'destination', 'class_type')
    search_fields = ('name', 'capacity_group')
    filter_horizontal = ('class_type',)

    def get_class_types(self, obj):
        return ", ".join([ctype.name for ctype in obj.class_type.all()])

    get_class_types.short_description = 'Class Types'


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'train_name', 'source', 'destination', 'status', 'travel_date', 'selected_seats', 'passenger_count', 'total_fare']
    list_filter = ['status', 'travel_date']
    search_fields = ['user__username', 'train_name', 'source', 'destination']

    def passenger_count(self, obj):
        return obj.passengers.count()

    passenger_count.short_description = 'Passengers'


@admin.register(BillingInfo)
class BillingInfoAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'email', 'phone', 'booking']


@admin.register(BookingDetail)
class BookingDetailAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking', 'train', 'source', 'destination', 'travel_date', 'total_fare']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'booking', 'pay_amount', 'pay_method', 'phone', 'trxid', 'status']


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ['id', 'ticket_uid', 'booking', 'passenger', 'seat_number', 'user', 'train_name', 'source', 'destination', 'travel_date', 'class_type', 'fare']


@admin.register(Passenger)
class PassengerAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking', 'full_name', 'gender', 'age', 'seat_number']
    list_filter = ['gender', 'booking__travel_date']
    search_fields = ['full_name', 'booking__id', 'booking__user__username']


@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking', 'phone_number', 'amount', 'trx_id', 'result_code']
    search_fields = ['trx_id', 'phone_number']


@admin.register(ContactForm)
class ContactFormAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'email']


@admin.register(ContactNumber)
class ContactNumberAdmin(admin.ModelAdmin):
    list_display = ['id', 'phone']


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = all_fields(CustomUser)


@admin.register(SeatAllocation)
class SeatAllocationAdmin(admin.ModelAdmin):
    list_display = ['id', 'train', 'class_type', 'travel_date', 'seat_number', 'booking', 'created_at']
    list_filter = ['train', 'class_type', 'travel_date']
    search_fields = ['booking__id', 'class_type__name']


@admin.register(TrainClassCapacity)
class TrainClassCapacityAdmin(admin.ModelAdmin):
    list_display = ['id', 'train', 'class_type', 'seat_count', 'created_at']
    list_filter = ['train', 'class_type']
    search_fields = ['train__name', 'class_type__name']
