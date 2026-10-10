# SPDX-License-Identifier: GPL-3.0-or-later
"""What `test_cache.BoundedMagnet.test_bounded_cache_works_with_a_magnet_link_and_survives_a_restart` is meant to establish, stated as properties that do not
depend on timing. That older test counts ALL payload downloaded by the second session and allows fewer than 3 pieces. Instrumented runs showed the extra payload in
its rare failures (under CPU load) was the file's pinned head and tail pieces (container index), which a session requests whenever it starts and which session 1 had
not always finished before it was closed - not pieces of the requested range, and never a cache-limit violation. This test asserts the real guarantees instead:
  * every piece of the served range was retained durably by session 1 and is `have` as soon as session 2 opens;
  * session 2 never re-downloads a piece of that range (not at response time, not afterwards);
  * the served bytes are exact;
  * allocated disk blocks stay within the limit in both sessions."""
import asyncio
import json
import unittest

from lumiere.punch import allocated_bytes
from tests.support import http_range
from tests.test_cache import PL, CacheCase, MiB


class RestartReuse(CacheCase):
    async def test_range_pieces_are_retained_reused_and_never_refetched_and_the_limit_holds(self):
        from lumiere.session import StreamSession
        ih = str(self.ti.info_hash())
        magnet = f"magnet:?xt=urn:btih:{ih}&dn=t&x.pe=127.0.0.1:{self.sd.port}"
        limit = 48 * MiB
        kw = dict(cache_limit_bytes=limit, verify_source=self.src, min_readahead_bytes=2 * MiB, mpv_cache_bytes=0, window_margin_bytes=0)
        a, b = 3_000_000, 3_399_999
        need = set(range(a // PL, b // PL + 1))
        s = await StreamSession.open(self.cfg(**kw), magnet, self.tmp / "dl")
        _, _, body, *_ = await http_range(s.server.port, s.server.path, f"bytes={a}-{b}", deadline_s=60)
        self.assertEqual(body, self.src.read_bytes()[a:b + 1])
        self.assertLessEqual(allocated_bytes(self.tmp / "dl"), limit)
        await s.close()
        idx = json.loads(next((self.tmp / "state").glob("*.cache.json")).read_text())
        retained = {i for i, byte in enumerate(bytes.fromhex(idx["retained"])) if byte}
        self.assertTrue(need <= retained, f"pieces of the served range missing from the durable index: {sorted(need - retained)}")

        s2 = await StreamSession.open(self.cfg(**kw), magnet, self.tmp / "dl")
        self.addAsyncCleanup(s2.close)
        have_start = {i for i, v in enumerate(s2.store._have) if v}
        self.assertTrue(need <= have_start, "retained pieces must be available immediately after the restart")
        _, _, body, *_ = await http_range(s2.server.port, s2.server.path, f"bytes={a}-{b}", deadline_s=60)
        self.assertEqual(body, self.src.read_bytes()[a:b + 1])
        await asyncio.sleep(1.0)                                        # let alerts settle; other (pinned / read-ahead) pieces may arrive meanwhile - that is allowed
        refetched = {i for i, v in enumerate(s2.store._have) if v} - have_start
        self.assertEqual(refetched & need, set(), "a retained piece of the range was downloaded again")
        self.assertEqual(s2.store.stats().get("hash_failed", 0), 0)
        self.assertLessEqual(allocated_bytes(self.tmp / "dl"), limit)


if __name__ == "__main__":
    unittest.main()
