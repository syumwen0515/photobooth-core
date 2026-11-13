import asyncio
import time

from app import main


def test_ensure_thumb_dedups_and_limits_concurrency(tmp_path):
    calls = []
    active = {"now": 0, "max": 0}

    def fake_job(path):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        time.sleep(0.05)
        calls.append(path)
        path.write_bytes(b"x")
        active["now"] -= 1

    async def run():
        main._thumb_semaphore = asyncio.Semaphore(2)
        same = tmp_path / "same.webp"
        others = [tmp_path / f"o{i}.webp" for i in range(5)]
        await asyncio.gather(
            *[main._ensure_thumb(same, fake_job, same) for _ in range(5)],
            *[main._ensure_thumb(p, fake_job, p) for p in others],
        )

    asyncio.run(run())
    assert len(calls) == 6
    assert active["max"] <= 2
    assert not main._thumb_inflight


def test_broadcast_drops_stalled_connection():
    class Slow:
        async def send_json(self, _):
            await asyncio.sleep(10)

    class Ok:
        sent = None

        async def send_json(self, m):
            Ok.sent = m

    async def run():
        old = main.WS_SEND_TIMEOUT
        main.WS_SEND_TIMEOUT = 0.1
        try:
            mgr = main.ConnectionManager()
            slow, ok = Slow(), Ok()
            mgr.active_connections = {slow, ok}
            await mgr.broadcast({"a": 1})
            return mgr, ok
        finally:
            main.WS_SEND_TIMEOUT = old

    mgr, ok = asyncio.run(run())
    assert Ok.sent == {"a": 1}
    assert len(mgr.active_connections) == 1
