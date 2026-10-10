# Investigation: intermittent failure of `test_bounded_cache_works_with_a_magnet_link_and_survives_a_restart`

Status: **cause identified with reproducing evidence; the test's assumption is incorrect; no cache-guarantee violation was found.** The original test is left untouched (the public
candidate and this repository's engine were not modified); a deterministic replacement test is added. One caveat remains and is stated at the end.

## What failed, and what the numbers mean
`tests/test_cache.py::BoundedMagnet::test_bounded_cache_works_with_a_magnet_link_and_survives_a_restart` failed once in a full discovery run:
`AssertionError: 262144 not less than 196608 : retained pieces must be reused after a restart`.

* The cache limit in this test is **48 MiB (50 331 648 B)**. Neither number in the message is the cache limit.
* `196608 = 3 × 65536` is a *tolerance*: the test allows fewer than 3 pieces (piece length 64 KiB) of **payload downloaded by the second session** (`stats()["total_download"]`, taken right after the range response).
* `262144 = 4 × 65536` is the payload the second session had received at that instant: four pieces' worth, i.e. one piece over the tolerance.
* The test therefore measures *how much the restarted session re-downloaded*, not how much disk it used. The cache invariant (allocated blocks ≤ limit) is a different quantity and was checked separately.

## What the test does
Session 1 opens the torrent from a magnet link, requests bytes 3 000 000–3 399 999 (pieces 45–51), closes. Session 2 opens the same cache, reads the same range, and asserts it downloaded < 3 pieces.

## Evidence (instrumented replica of the test, same configuration, loopback swarm)
The replica records which pieces session 1 had made durable (the cache index), which pieces session 2 downloaded and where they lie, and the allocated-bytes invariant. Runs: 12 quiet, 16 under CPU load (16 busy loops on 8 cores), 40 under load with full classification.

| finding | result |
|---|---|
| pieces of the requested range (45–51) retained durably by session 1 | **7/7 in every run** |
| pieces of the requested range downloaded again by session 2 (at response time or 0.8 s later) | **0 in every run** |
| allocated disk blocks ≤ limit, after session 1 and after session 2 | **held in every run** (≈ 0.8–2 MiB used, limit 48 MiB) |
| runs in which session 2 downloaded any payload | quiet 0/12; under load 3/56 |
| runs that would violate the "< 3 pieces" assertion | 0/12 quiet; **2/56 under load** (256 387 B and 447 747 B), plus the original failure (262 144 B) in 1 full discovery run |
| which pieces the extra payload belonged to (classified runs) | **head pieces 0–15 and tail pieces 229–230** (second classified run: pieces 2–15) — never the range 45–51, never read-ahead beyond it |

## Mechanism
`lumiere/config.py` pins the container head and tail (`pin_head_bytes = 1 MiB` = pieces 0–15, `pin_tail_bytes = 512 KiB`): the scheduler requests them whenever a session starts, because players probe a file's header/index first. Session 1 closes immediately after the range
response, so how many of those pinned pieces it had completed (and made durable) before closing is a race: the instrumented runs show 14–32 pieces retained at close. Whatever session 1 did not finish, session 2 downloads at start-up, and those bytes are added to `total_download`. Under CPU load more
of them are still in flight when the test reads the counter, and the total can reach 3 pieces.
That is **timing sensitivity plus an incorrect assumption**: the test treats "any payload in session 2" as "retained pieces were not reused", but the payload belongs to pinned pieces unrelated to the range. The retention and reuse the test is meant to establish worked in every run.

## What was added (sandbox only)
`tests/test_cache_restart_reuse.py` asserts the real guarantees without timing dependence: every piece of the served range is in the durable index after session 1 closes, is available the moment session 2 opens, is **never** downloaded again, the bytes served are exact, no hash failure occurs, and allocated bytes stay within the limit in both sessions.
Evidence that it is stable and sensitive: 25/25 passes (5 quiet, 20 under load); **mutation tests** — disabling the durable flush, or forgetting retained pieces on reopen — each make it fail with the expected message.
The original test is unchanged and still can fail (it was not weakened and not deleted). Recommended for the maintainers: replace its assertion by the property-based one (or wait for the pinned pieces) — a decision for the project owner, not applied here.

## What remains unproven
The original failure (262 144 B) was observed in a full run that was not instrumented, so its exact composition (which four pieces) is **inferred, not observed**: it matches the mechanism in size and conditions and in the two classified reproductions, but it is not proven for that specific occurrence.
The related intermittent engine tests recorded earlier (`test_stalls` black-hole test; the magnet GUI player test) were not investigated here and remain unresolved.
