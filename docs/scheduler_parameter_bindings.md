# Scheduler parameter bindings

Snapshot schedules own their SQL bind values. Endpoint defaults remain useful for live requests and SQL preview, but scheduled execution never reads them. This separation prevents a request default from silently changing a recurring data window.

## Binding sources

Every parameter declared by the endpoint must have exactly one schedule binding. Extra or missing names are rejected with HTTP 422.

| Source | Supported parameter | Resolution |
|---|---|---|
| `literal` | Any type | A fixed value, validated through the endpoint's typed parameter schema |
| `null` | Optional only | An explicit bind whose value is SQL `NULL` |
| `run_date` | Date | The nominal run date in the schedule timezone |
| `relative_date` | Date | The run date plus `offset_days` |
| `window_start` | Date | Inclusive start of the configured calendar window |
| `window_end` | Date | Inclusive end of the configured calendar window |

The contract is deliberately declarative. Arbitrary Python, JavaScript, template, and SQL expressions are not evaluated.

## Calendar windows

All boundaries are inclusive and are calculated from the schedule's logical run date.

| Preset | Start | End |
|---|---|---|
| `previous_day` | Run date minus one day | Same day |
| `last_n_complete_days` | `N` complete days before the run date | Run date minus one day |
| `week_to_date` | Monday of the run-date week | Run date |
| `previous_week` | Monday of the previous week | Previous Sunday |
| `month_to_date` | First day of the run-date month | Run date |
| `previous_month` | First day of the previous month | Last day of the previous month |

Month and leap-year boundaries use calendar arithmetic, so previous month for a 2024-03-01 run resolves to 2024-02-01 through 2024-02-29.

## Example

This daily schedule queries the previous seven complete days and passes an optional store filter as SQL `NULL`:

```json
{
  "endpoint_id": "00000000-0000-0000-0000-000000000000",
  "schedule_type": "cron",
  "cron_expression": "0 6 * * *",
  "timezone": "Asia/Riyadh",
  "parameter_bindings": {
    "start_date": { "source": "window_start" },
    "end_date": { "source": "window_end" },
    "store_id": { "source": "null" }
  },
  "window": {
    "preset": "last_n_complete_days",
    "days": 7
  }
}
```

Before creating it, send the same timing and binding fields to:

```text
POST /api/v1/admin/schedules/preview
```

The response contains the next one to ten nominal fire times (three by default), logical dates, window boundaries, and resolved typed parameters.

## Logical time, retries, and manual runs

Cron expressions and run dates are evaluated in the schedule's IANA timezone. Normal execution uses the persisted nominal `next_run_at` as `scheduled_for`, not the wall-clock time at which a delayed job starts. Job runs store the resolved context and a binding-configuration hash. A unique `(schedule_id, scheduled_for)` key prevents duplicate execution of the same logical run.

`Run now` derives its logical date from the current time by default. An administrator can replay a particular business date without editing the schedule:

```json
POST /api/v1/admin/schedules/{schedule_id}/run

{
  "logical_date": "2026-08-30"
}
```

The supplied date is interpreted at midnight in the schedule timezone and is recorded with trigger source `manual`.

## Endpoint changes

An attached schedule and its endpoint form one validated configuration. While a schedule exists, endpoint updates must keep the endpoint in snapshot mode and preserve SQL/parameter names and types that the stored bindings can resolve. Incompatible updates return HTTP 422 without changing the endpoint. Delete or update the schedule first when intentionally changing that contract.

## Existing schedules

The Alembic migration converts existing endpoint defaults into schedule-local bindings:

- `today` becomes `run_date`.
- `yesterday` becomes `relative_date` with `offset_days: -1`.
- Explicit SQL `NULL` remains `null`.
- Fixed defaults become `literal`.

A legacy schedule parameter with no resolvable default is left unbound and fails clearly until an administrator selects a schedule source. The migration never invents a value.
