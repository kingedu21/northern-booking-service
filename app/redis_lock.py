from contextlib import contextmanager
from uuid import uuid4

from django.core.cache import cache


def _lock_key(train_scope, class_type_id, travel_date, seat_number):
    return f"seat_lock:{train_scope}:{class_type_id}:{travel_date}:{seat_number}"


@contextmanager
def acquire_seat_locks(train_id, class_type_id, travel_date, seat_numbers, ttl_seconds=30):
    """
    Acquire per-seat short-lived locks using Redis-backed cache.
    Yields (ok, conflicts) where conflicts are seats currently locked by others.
    """
    token = str(uuid4())
    acquired = []
    conflicts = []

    for seat in seat_numbers:
        key = _lock_key(train_id, class_type_id, travel_date, int(seat))
        # cache.add is atomic for Redis: succeeds only if key does not exist.
        if cache.add(key, token, timeout=ttl_seconds):
            acquired.append(key)
        else:
            conflicts.append(int(seat))

    try:
        yield (len(conflicts) == 0, sorted(conflicts))
    finally:
        # Release only locks owned by this request token.
        for key in acquired:
            if cache.get(key) == token:
                cache.delete(key)
