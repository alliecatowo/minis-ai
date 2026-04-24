# Agreement Scorecard UI Contract

The owner-visible scorecard on the mini profile page uses the backend summary endpoint at:

```text
GET /api/minis/{mini_id}/agreement-scorecard-summary
```

Expected response shape:

```json
{
  "mini_id": "mini_123",
  "username": "alliecatowo",
  "cycles_count": 12,
  "approval_accuracy": 0.83,
  "blocker_precision": 0.71,
  "comment_overlap": 0.64,
  "trend": {
    "direction": "up",
    "delta": 0.03
  }
}
```

Notes:

- The route is owner-only. The UI only renders the card for the owner.
- `cycles_count` of `0` is a valid empty state, with the metric fields set to `null`.
- `trend.direction` is one of `up`, `down`, `flat`, or `insufficient_data`.
- `trend.delta` is the recent overall score delta as a decimal and is `null` when trend data is insufficient.
- Until the backend route is merged, the frontend renders an explicit dependency state instead of failing silently on a `404`.
