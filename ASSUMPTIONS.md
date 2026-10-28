# Assumptions

**Scope**
- Single currency; amounts have no currency field.
- No authentication or authorization. Anyone who can reach the API can use any account.
- Accounts and transactions are never deleted or edited. Corrections are made with a new transaction.
- The dashboard at `/` (`app/static/`) is a convenience client for the same public endpoints. It has no
  authentication of its own and is not part of the versioned API contract. It generates references in the
  browser (the user never types one), hides them under **Advanced details**, and keeps an uncertain request
  in `localStorage` so a refresh cannot lose the reference needed for a safe retry.

**Money**
- Amounts are strictly greater than 0, with at most 2 decimal places and at most 18 digits in total
  (16 before the decimal point). Anything else is a 422 `INVALID_AMOUNT`; the API never silently rounds.
  Trailing zeros are fine (`"10.000"` is exactly 10.00).
- Amount strings must be plain ASCII decimals (`"10"`, `"10.5"`, `"10.50"`). Scientific notation, underscores,
  signs, a bare `.5` / `5.` and non-ASCII digits are rejected. Surrounding whitespace is trimmed.
- Strings are the recommended format. JSON numbers are accepted for amounts **below 10,000,000,000,000**,
  where a 64-bit float represents 2-decimal values faithfully. Larger JSON numbers are rejected (422) because
  digits may already have been lost before the API sees them; send those as strings.
- Balances can never be negative (also enforced by a DB `CHECK`). Debiting the exact balance is allowed.
- The maximum balance is `9999999999999999.99`. A credit or transfer that would exceed it fails with
  `409 BALANCE_LIMIT_EXCEEDED` and changes nothing.

**Accounts**
- `id` is a server-generated UUID. `created_at` is server-generated.
- The client can't set `id`, `balance` or `created_at`: unknown fields are rejected with 422 instead of being ignored,
  so a client sending `balance` finds out immediately.
- `name` is trimmed, must be non-empty, max 255 characters.

**Transactions and idempotency**
- `reference_id` is trimmed, 1–128 characters, and unique per account (not globally).
- A repeat with the same `reference_id` **and** the same type, amount and description is treated as a retry:
  `200` with the original transaction and `"duplicate": true`. No new row, no balance change.
- A repeat with the same `reference_id` but any different type, amount or description is a client bug: `409 REFERENCE_ID_CONFLICT`.
- A request rejected for insufficient balance stores nothing, so its `reference_id` can be reused.
- A retry of a request that *succeeded* always returns the original, even if the balance has since dropped
  below the amount (the duplicate check runs before the balance check).
- `description` is optional; empty/whitespace is stored as null. Max 500 characters.
- `reference_id` is **caller-supplied on purpose**. It is the idempotency key, not a server id. Only the
  caller can repeat the same value on a retry, which is what makes duplicate detection possible. A missing
  reference is a 422; the server never invents one. Clients should generate a UUID per operation and reuse
  it when retrying (the dashboard does this automatically, so the user never types it).

**History**
- Ordered newest first by write order (`seq`), not by timestamp. See `docs/ARCHITECTURE.md` section 10.
- `limit` is 1–100 (default 20), `offset` ≥ 0. Invalid values return 422 `INVALID_PAGINATION`.
- `type` accepts `credit` or `debit`; omitted returns both. Transfer legs appear as normal debit/credit entries with a `transfer_id`.

**Transfers (bonus)**
- Same rules as transactions for amount and reference.
- `reference_id` is scoped to the **source** account (`UNIQUE (from_account_id, reference_id)`).
- Source and destination must differ (422) and both must exist (404).
- A retry is identical only if source, destination, amount and description all match.

**HTTP status choices**
- 422 for anything wrong with the request itself (bad JSON, bad types, bad pagination, malformed UUID).
- 404 for a well-formed id that doesn't exist.
- 409 for conflicts with current state: insufficient balance, or a reference reused with a different payload.
  (422 for insufficient balance would also be defensible; 409 was chosen and is used consistently.)
