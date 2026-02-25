from datetime import date
from decimal import Decimal
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Booking, ClassType, SeatAllocation, Station, Train, TrainClassCapacity


class ClassTypeFareCalculationTests(TestCase):
    def test_calculate_total_fare_uses_custom_adult_and_child_prices(self):
        class_type = ClassType.objects.create(
            name='First Class',
            price=Decimal('100.00'),
            adult_price=Decimal('120.00'),
            child_price=Decimal('60.00'),
        )
        total = class_type.calculate_total_fare(adults=2, children=1)
        self.assertEqual(total, Decimal('300.00'))

    def test_calculate_total_fare_falls_back_to_base_price(self):
        class_type = ClassType.objects.create(
            name='Economy',
            price=Decimal('80.00'),
        )
        total = class_type.calculate_total_fare(adults=1, children=2)
        self.assertEqual(total, Decimal('240.00'))


class BookingRedirectBackToSearchTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='alice',
            password='testpass123',
            email='alice@example.com',
        )
        self.client.force_login(self.user)

        self.source = Station.objects.create(name='Source', code='SRC')
        self.destination = Station.objects.create(name='Destination', code='DST')
        self.class_type = ClassType.objects.create(name='Economy', price=Decimal('50.00'))
        self.train = Train.objects.create(
            name='Intercity 1',
            source=self.source,
            destination=self.destination,
        )
        self.train.class_type.add(self.class_type)
        TrainClassCapacity.objects.create(
            train=self.train,
            class_type=self.class_type,
            seat_count=2,
        )

        self.travel_date = date(2026, 2, 22)
        self.base_booking_params = {
            'train': self.train.name,
            'source': self.source.name,
            'destination': self.destination.name,
            'source_id': str(self.source.id),
            'destination_id': str(self.destination.id),
            'date': self.travel_date.isoformat(),
            'departure': '09:00',
            'arrival': '12:00',
            'train_id': str(self.train.id),
            'tp': '1',
            'pa': '1',
            'pc': '0',
            'ctype': str(self.class_type.id),
        }

    def expected_availability_redirect(self):
        query = urlencode({
            'rfrom': str(self.source.id),
            'to': str(self.destination.id),
            'date': self.travel_date.isoformat(),
            'ctype': str(self.class_type.id),
            'pa': '1',
            'pc': '0',
        })
        return f"{reverse('available_train')}?{query}"

    def test_conflicting_seat_redirects_back_to_availability(self):
        existing = Booking.objects.create(
            user=self.user,
            train_name=self.train.name,
            source=self.source.name,
            destination=self.destination.name,
            class_type=self.class_type,
            travel_date=self.travel_date,
        )
        SeatAllocation.objects.create(
            train=self.train,
            booking=existing,
            class_type=self.class_type,
            travel_date=self.travel_date,
            seat_number=1,
        )

        params = dict(self.base_booking_params)
        params['selected_seats'] = ['1']
        response = self.client.get(reverse('booking'), params)

        self.assertRedirects(response, self.expected_availability_redirect(), fetch_redirect_response=False)

    def test_invalid_selection_redirects_back_to_availability(self):
        params = dict(self.base_booking_params)
        params['selected_seats'] = ['3']

        response = self.client.get(reverse('booking'), params)

        self.assertRedirects(response, self.expected_availability_redirect(), fetch_redirect_response=False)

    def test_missing_search_context_falls_back_to_home(self):
        params = dict(self.base_booking_params)
        params['source_id'] = ''
        params['selected_seats'] = []

        response = self.client.get(reverse('booking'), params)

        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

    def test_grouped_duplicate_trains_share_seat_pool(self):
        duplicate = Train.objects.create(
            name='Intercity 1 (return)',
            source=self.source,
            destination=self.destination,
            capacity_group='IC1',
        )
        self.train.capacity_group = 'IC1'
        self.train.save(update_fields=['capacity_group'])
        duplicate.class_type.add(self.class_type)
        TrainClassCapacity.objects.create(
            train=duplicate,
            class_type=self.class_type,
            seat_count=2,
        )

        existing = Booking.objects.create(
            user=self.user,
            train_name=self.train.name,
            source=self.source.name,
            destination=self.destination.name,
            class_type=self.class_type,
            travel_date=self.travel_date,
        )
        SeatAllocation.objects.create(
            train=self.train,
            booking=existing,
            class_type=self.class_type,
            travel_date=self.travel_date,
            seat_number=1,
        )

        params = dict(self.base_booking_params)
        params['train'] = duplicate.name
        params['train_id'] = str(duplicate.id)
        params['selected_seats'] = ['1']

        response = self.client.get(reverse('booking'), params)

        self.assertRedirects(response, self.expected_availability_redirect(), fetch_redirect_response=False)
