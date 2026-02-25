from django.urls import path
from .views import (
    Home, AvailableTrain, Bookings, confirm_booking, BookingHistory,
    BookingDetails, Tickets, CancelBooking, signup, user_login, logout,
    Contact, Feedbacks, VerifyTicket, Profile,
    process_payment, stk_push, mpesa_callback, mpesa_status, seat_availability
)

urlpatterns = [
    path('', Home.as_view(), name='home'),
    path('available_train/', AvailableTrain.as_view(), name='available_train'),
    path('booking/', Bookings.as_view(), name='booking'),
    path('confirm-booking/<int:booking_id>/', confirm_booking, name='confirm_booking'),
    path('booking_history/', BookingHistory.as_view(), name='booking_history'),
    path('booking_detail/<int:pk>/', BookingDetails.as_view(), name='booking_detail'),
    path('tickets/<int:pk>/', Tickets.as_view(), name='tickets'),
    path('cancel_booking/', CancelBooking.as_view(), name='cancel_booking'),
    path('signup/', signup, name='signup'),
    path('login/', user_login, name='login'),
    path('logout/', logout, name='logout'),
    path('contact/', Contact.as_view(), name='contact'),
    path('feedback/', Feedbacks.as_view(), name='feedback'),
    path('verify_ticket/', VerifyTicket.as_view(), name='verify_ticket'),
    path('profile/', Profile.as_view(), name='profile'),
    path('process_payment/', process_payment, name='process_payment'),
    path('seat_availability/', seat_availability, name='seat_availability'),
    path('mpesa_status/', mpesa_status, name='mpesa_status'),
    path('stk_push/', stk_push, name='stk_push'),
    path('mpesa_callback/', mpesa_callback, name='mpesa_callback'),
]
