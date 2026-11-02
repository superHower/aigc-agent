import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from backend.main import app
from backend.services import credits, membership
from backend.services.admission import Admission
from tests.test_v4_credits import ledger
from tests.test_v4_identity import identity_app, signup
from tests.test_v4_migrations import postgres_store


def test_concurrent_renewal_and_idempotency(ledger):
    initial = datetime.now(timezone.utc) + timedelta(days=5)
    with ledger.transaction() as db:
        db.execute('UPDATE users SET membership_expires_at=? WHERE id=?', (initial.isoformat(), 'user'))

    def renew(data):
        days, key = data
        with ledger.transaction() as db:
            credits.begin(db)
            return membership.renew(db, 'user', days, key)

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(renew, [(7, 'week'), (30, 'month'), (7, 'week')]))
    result = membership.status(ledger, 'user')
    assert datetime.fromisoformat(result['expires_at']) == initial + timedelta(days=37)
    assert result['active'] and result['concurrency'] == 3
    with pytest.raises(HTTPException) as error:
        renew((8, 'week'))
    assert error.value.status_code == 409
    before = result['expires_at']
    with ledger.transaction() as db:
        credits.begin(db)
        credits.grant(db, 'user', 30, 'paid', 'pack')
    assert membership.status(ledger, 'user')['expires_at'] == before
    with ledger.transaction() as db:
        db.execute('UPDATE users SET membership_expires_at=?', ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
    assert not membership.status(ledger, 'user')['active']
    assert credits.balance(ledger, 'user')['available'] == 33
    renewed = datetime.fromisoformat(renew((7, 'new-week')))
    assert 6.99 < (renewed-datetime.now(timezone.utc)).total_seconds()/86400 <= 7


def test_admission_joint_capacity_fairness_and_expiry(ledger):
    async def scenario():
        scheduler = Admission(ledger)
        busy = asyncio.Semaphore(0)
        free = asyncio.Semaphore(3)
        started = []
        release = asyncio.Event()

        async def work(label, owner, capacity):
            async with scheduler.slot(owner, capacity):
                started.append(label)
                await release.wait()

        # A job stuck behind a busy channel must not consume the user's quota.
        blocked = asyncio.create_task(work('blocked', 'user', busy))
        running = asyncio.create_task(work('first', 'user', free))
        await asyncio.sleep(.1)
        assert started == ['first'] and scheduler.running['user'] == 1
        second = asyncio.create_task(work('second', 'user', free))
        await asyncio.sleep(.1)
        assert started == ['first']
        with ledger.transaction() as db:
            db.execute('UPDATE users SET membership_expires_at=?', ((datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),))
        await asyncio.sleep(.1)
        assert started == ['first', 'second']
        with ledger.transaction() as db:
            db.execute('UPDATE users SET membership_expires_at=?', ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),))
        third = asyncio.create_task(work('third', 'user', free))
        await asyncio.sleep(.1)
        # Expiry doesn't stop either in-flight request, and blocks new starts.
        assert started == ['first', 'second']
        blocked.cancel()
        await asyncio.gather(blocked, return_exceptions=True)
        release.set()
        await asyncio.gather(running, second, third)
        assert started == ['first', 'second', 'third']
        assert not scheduler.running and not scheduler.waiting and free._value == 3

        # A second user gets the next available slot ahead of a queued same-user burst.
        with ledger.transaction() as db:
            db.execute("INSERT INTO users (id,username,password_hash,role,created_at) VALUES ('other','other','x','user',?)", (datetime.now(timezone.utc).isoformat(),))
        one = asyncio.Semaphore(1)
        order = []
        async def fair(owner, label):
            async with scheduler.slot(owner, one):
                order.append(label)
                await asyncio.sleep(.03)
        await asyncio.gather(fair('user', 'a'), fair('user', 'b'), fair('other', 'c'))
        assert order == ['a', 'c', 'b']
    asyncio.run(scenario())
