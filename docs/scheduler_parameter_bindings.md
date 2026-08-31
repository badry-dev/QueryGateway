# Endpoint, scheduler, and snapshot parameter contracts

QueryGateway treats the same SQL bind name differently depending on where it is used. Keeping these contexts separate prevents a preview value or request default from silently changing a recurring snapshot window.

| Context | Value source | Persisted? | Purpose |
|---|---|---|---|
| SQL preview | Temporary sample entered in the endpoint wizard | No | Execute a safe sample query and discover output columns |
| Live data request | Authenticated HTTP query string, with optional endpoint default | Endpoint default only | Bind and execute the Oracle query for this request |
| Snapshot schedule | Schedule-owned declarative parameter binding | Yes, on the schedule | Decide which rows Oracle loads into each snapshot |
| Snapshot data request | Authenticated HTTP query string plus endpoint `snapshot_filter` mappings | Mapping only | Select a covering retained snapshot and filter its cached rows |

## SQL preview and live request rules

- A bind placeholder must be outside SQL string quotes: use `store_id = :store_id`, not
  `store_id = ':store_id'`. Text inside single quotes is a SQL literal and is not detected as a
  bind parameter.
- Every parameter marked `required` must be supplied by both live and snapshot callers. A stored
  endpoint default never weakens that request contract.
- An omitted optional live parameter may use a typed literal default, explicit SQL `NULL`, or the
  dynamic date default `today` or `yesterday`. An optional parameter with no default resolves to
  `NULL`.
- Date requests accept `YYYY-MM-DD` and `DD-MM-YYYY` and normalize to a Python `date` before
  binding. Boolean requests accept `true`, `false`, `1`, `0`, `yes`, or `no`.
- Preview sample values are request-local and never become endpoint defaults or schedule
  bindings.

For example, a required date range and optional store filter are supplied as ordinary query
parameters:

```text
GET /api/v1/data/store-orders?start_date=2026-08-01&end_date=31-08-2026&store_id=10
```

Invalid or missing declared values return HTTP 422 before Oracle execution or snapshot lookup.

## Schedule-owned parameter bindings

Snapshot schedules own their SQL bind values. Scheduled execution never reads endpoint defaults.

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

The response contains the next one to ten nominal fire times (three by default), logical dates,
window boundaries, and resolved typed parameters.

## Snapshot request filters and coverage

Schedule bindings decide which rows Oracle loads into a snapshot. Authenticated data-request
parameters decide which rows are returned from that cache. Every parameterized snapshot endpoint
must explicitly map each request parameter to a cached output column after `column_map` renaming
and one whitelisted comparison:

| Operator | Row selection | Coverage requirement |
|---|---|---|
| `eq` | Cached column equals the request value | Scheduled value equals the request value |
| `gte` | Cached column is greater than or equal to the request value | Scheduled lower bound is less than or equal to the request lower bound |
| `lte` | Cached column is less than or equal to the request value | Scheduled upper bound is greater than or equal to the request upper bound |

Example endpoint parameter schema:

```json
{
  "start_date": {
    "type": "date",
    "required": true,
    "snapshot_filter": { "column": "business_date", "operator": "gte" }
  },
  "end_date": {
    "type": "date",
    "required": true,
    "snapshot_filter": { "column": "business_date", "operator": "lte" }
  },
  "store_id": {
    "type": "integer",
    "required": false,
    "default_is_null": true,
    "snapshot_filter": {
      "column": "store_id",
      "operator": "eq",
      "null_means_all": true
    }
  }
}
```

`null_means_all` is valid only for `eq` on an optional parameter. It means a schedule run whose
resolved value is SQL `NULL` covers every requested value for that parameter. Whenever an optional
request parameter is omitted, the selector requires a retained run where that parameter also
resolved to SQL `NULL`; a fixed-value snapshot is only a subset and cannot satisfy the request.
Without `null_means_all`, that NULL-resolved snapshot represents the query's exact NULL semantics
rather than all possible values. This flag does not make a required HTTP parameter optional. A
parameter such as `store_id` is an ordinary row filter here; it is not tenant authorization.
Authentication and authorization remain the responsibility of the endpoint's configured auth
method.

The data plane checks retained snapshots newest first and selects the newest snapshot whose
persisted job-run parameters cover the complete request. It then applies every configured mapping
to the cached rows using the parameter's declared type. Date columns containing Oracle
DATE/TIMESTAMP ISO strings are normalized to dates before comparison. Behavior is explicit:

- Missing or invalid required parameters return HTTP 422 with the field in `detail`.
- Lower and upper mappings for the same cached column must declare the same parameter type.
- A lower bound greater than its upper bound returns HTTP 422 with `code=invalid_parameter_range`.
- A valid request outside all retained coverage returns HTTP 422 with `code=snapshot_out_of_coverage`.
- A request inside coverage with no matching business rows returns HTTP 200 with `data: []`.
- An endpoint created before this contract without complete mappings returns HTTP 422 with `code=snapshot_filter_not_configured`; add mappings through the endpoint edit dialog or admin update API.
- A mapping that does not exist in a non-empty cached row returns HTTP 422 with `code=snapshot_filter_column_unavailable`.
- No retained snapshot still returns HTTP 503.

Representative stable error bodies are:

```json
{
  "code": "snapshot_out_of_coverage",
  "detail": "Requested parameters are outside retained snapshot coverage."
}
```

```json
{
  "code": "invalid_parameter_range",
  "detail": "Snapshot filter lower bound must not exceed its upper bound."
}
```

The mapping is stored inside the endpoint's existing JSON parameter schema, so it requires no
relational database migration. Schedule-owned bindings, timezone, logical-run fields, resolved
parameter audit data, and the `(schedule_id, scheduled_for)` idempotency constraint were added by
Alembic revision `e4a6c2d9f801`.

## Logical time, retries, and manual runs

Cron expressions and run dates are evaluated in the schedule's IANA timezone. Normal execution
uses the persisted nominal `next_run_at` as `scheduled_for`, not the wall-clock time at which a
delayed job starts. Job runs store the resolved context and a binding-configuration hash. A unique
`(schedule_id, scheduled_for)` key prevents duplicate execution of the same logical run.

`Run now` derives its logical date from the current time by default. An administrator can replay a particular business date without editing the schedule:

```json
POST /api/v1/admin/schedules/{schedule_id}/run

{
  "logical_date": "2026-08-30"
}
```

The supplied date is interpreted at midnight in the schedule timezone and is recorded with trigger source `manual`.

## Endpoint changes

An attached schedule and its endpoint form one validated configuration. While a schedule exists,
endpoint updates must keep the endpoint in snapshot mode and preserve SQL/parameter names and
types that the stored bindings can resolve. Incompatible updates return HTTP 422 without changing
the endpoint. Delete or update the schedule first when intentionally changing that contract.

## Existing schedules

The Alembic migration converts existing endpoint defaults into schedule-local bindings:

- `today` becomes `run_date`.
- `yesterday` becomes `relative_date` with `offset_days: -1`.
- Explicit SQL `NULL` remains `null`.
- Fixed defaults become `literal`.

A legacy schedule parameter with no resolvable default is left unbound and fails clearly until an
administrator selects a schedule source. The migration never invents a value.
