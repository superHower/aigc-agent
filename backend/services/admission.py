"""Single-process admission: reserve user and channel capacity together, rotate users."""
import asyncio
from collections import Counter
from contextlib import asynccontextmanager

from backend.services.membership import status


class Admission:
    def __init__(self, store, ordinary=1, member=3):
        self.store = store
        self.ordinary = ordinary
        self.member = member
        self.running = Counter()
        self.waiting = []
        self.last_user = None

    @asynccontextmanager
    async def slot(self, user_id, semaphore, runtime=None):
        ticket = (object(), user_id, semaphore, runtime)
        self.waiting.append(ticket)
        admitted = False
        try:
            while True:
                eligible = []
                for candidate in self.waiting:
                    _, owner, capacity, channel = candidate
                    if channel and channel.broken.is_set():
                        # Let the regular channel error path finalize/retry this job.
                        eligible.append(candidate)
                        continue
                    if capacity.locked():
                        continue
                    limit = status(self.store, owner, self.ordinary, self.member)['concurrency'] if owner else None
                    if owner and self.running[owner] >= limit:
                        continue
                    eligible.append(candidate)
                chosen = next((c for c in eligible if c[1] != self.last_user), eligible[0] if eligible else None)
                if chosen is ticket:
                    # No await that can suspend between checking and reserving these resources.
                    if not (runtime and runtime.broken.is_set()):
                        await semaphore.acquire()
                        admitted = True
                        if user_id:
                            self.running[user_id] += 1
                    self.waiting.remove(ticket)
                    self.last_user = user_id
                    break
                await asyncio.sleep(0.05)
            yield
        finally:
            if ticket in self.waiting:
                self.waiting.remove(ticket)
            if admitted:
                semaphore.release()
                if user_id:
                    self.running[user_id] -= 1
                    if not self.running[user_id]:
                        del self.running[user_id]
