# Agreement Scorecard UI Contract

The owner-visible scorecard on the mini profile page expects a backend summary endpoint at:

```text
GET /agreement/{username}
```

Expected response shape:

```json
{
  "username": "alliecatowo",
  "cycle_count": 12,
  "metrics": {
    "approval_accuracy": { "value": 0.83, "trend": 0.08 },
    "blocker_precision": { "value": 0.71, "trend": -0.02 },
    "comment_f1": { "value": 0.64, "trend": 0.03 }
  },
  "updated_at": "2026-04-24T18:42:00Z"
}
```

Notes:

- `cycle_count` of `0` is a valid empty state.
- `trend` is optional and represents recent delta in percentage points as a decimal.
- Until this endpoint is merged, the frontend renders an explicit dependency state instead of failing silently.
