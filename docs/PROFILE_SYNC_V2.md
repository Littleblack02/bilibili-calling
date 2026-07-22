# Profile Sync V2

V2 profile sync is enabled by default; set `PROFILE_SYNC_V2_ENABLED=false` to
roll it back. Each channel request records an
idempotent `ProfileSyncRun` with session, channel, channel kind, status,
capability status, timing, HTTP status, item/page counts, cursor, bounded error
summary, full-snapshot flag and schema version.

Channels are classified as:

- snapshot: favorites, subscriptions, followings, watch-later, collections and
  other current-state lists;
- event stream: video/live history and dynamic feed.

Every normalized signal records `last_seen_sync_id`. Only a successful,
exhausted snapshot run may deactivate active rows not seen in that run. Partial,
capped, timed-out, rate-limited, auth-required or schema-error runs retain old
rows. Event streams are never snapshot-invalidated.

The shared `PageNumberPaginator`, `CursorPaginator` and `OffsetPaginator` enforce
page/item limits, request timeouts, recent-event windows and per-page rate
limits. HTTP/API 429 retries use exponential backoff with jitter; authentication
failure stops queued channels for the same account. Cursors and capability
states (`working`, `degraded`, `auth_required`, `unavailable`, `schema_changed`)
remain available in the profile's channel-sync status.

Recorded fixtures are deidentified and cover every declared supported channel.
Tests cover multi-page and empty results, missing fields, nonzero codes, rate
limits, authentication failure, timeouts and non-JSON/HTML schema changes. The
capability matrix explicitly keeps full-account likes, coins and lifetime
completion history `unavailable`; it never invents those signals.

## Channel collection policy

| Channel | Kind | Strategy / bound | Full-snapshot rule |
| --- | --- | --- | --- |
| favorites | snapshot | page number, 20/page, 50 pages, 1,000 items | only after the selected folder is exhausted |
| bangumi | snapshot | page number, 20/page, 30 pages, 600 items | only after the API list is exhausted |
| cinema | snapshot | complete folder list plus 50/page per matching folder, 300 aggregate items | all folder reads must exhaust; hitting the aggregate cap makes it partial |
| history | event stream | page number, at most the requested recent sample, 30-day window | never invalidates snapshot data |
| watchlater | snapshot | documented single-list response, 1,000-item safety bound | a successful single-list response is complete |
| followings | snapshot | page number, 50/page, 40 pages, 2,000 items | only after pagination is exhausted |
| subscribed_tags | snapshot | page number, 50/page | only after pagination is exhausted |
| favorite_collections | snapshot | page number, 50/page | only after pagination is exhausted |
| favorite_topics | snapshot | page number, 16/page | only after pagination is exhausted |
| favorite_articles | snapshot | page number, 30/page | only after pagination is exhausted |
| favorite_courses | snapshot | page number, 30/page | only after pagination is exhausted |
| favorite_notes | snapshot | page number, 30/page | only after pagination is exhausted |
| courses | snapshot | page number, 30/page | only after pagination is exhausted |
| special_followings / whisper_followings | snapshot | page number, 50/page | only after pagination is exhausted |
| fan_medals | snapshot | one bounded page | partial if the response indicates more data |
| manga | snapshot | POST body page number, 30/page | only after pagination is exhausted |
| live_history | event stream | page number, recent 30-day window | never snapshot-invalidated |
| dynamic_feed | event stream | cursor, 20/page, 10 pages/200 items, recent 14-day window | exposure-only; never snapshot-invalidated |

All bounds are safety limits, not claims that the account has no more data.
Reaching a page/item/time bound leaves `full_snapshot=false`, so a capped run
cannot deactivate older signals. Core collectors retain an empty successful
snapshot (so removals can be represented) but keep the prior local list when
the channel status is failed, timed out, rate limited, authentication required,
or schema changed.
