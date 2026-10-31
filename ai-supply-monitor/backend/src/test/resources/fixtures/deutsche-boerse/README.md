# Deutsche Börse fixtures

`DETR-posttrade-2026-10-29T08_01.json.gz` is **synthetic**: hand-written records in the documented post-trade
layout, built to cover the parser's edge cases (several trades per minute out of order, a string-typed price,
a cancellation, an untracked ISIN, a record without a price).

It is not a recorded real payload. Add one next to it (download any current `DETR-posttrade-*.json.gz` from the
file service) and point a contract test at it before trusting the field mapping in `PostTradeParser`.
