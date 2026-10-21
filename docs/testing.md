# Testing against a live instance

The unit suite (`uv run pytest`) drives the server in memory with mocked HTTP. This page covers the checks that need a
real instance: which identities to test with, what each one should see, and how to read the results. Releases run
them as part of [RELEASING](../RELEASING.md) step 2.

Nothing is installed on the instance. Each identity is an integration user with roles and an API key or OAuth client,
and credentials come only from the environment, started under a secret-store launcher (never from a file or the
command line).

## Identity tiers

What a tool can do depends on the ServiceNow identity behind it, so one identity tests one tier. Use four:

| Tier | Roles | Auth | Tools listed, no flag | Expected refusals |
|---|---|---|---|---|
| Read-only, API key | `itil`, `snc_read_only` | API key, with a REST API access policy for Table API GET only | 13 | 401 on the Aggregate API (`aggregate_records`) and on single-record GET (`get_record`, `get_ci`); the 401 names the `list_records` call that still works. 403 on `get_table_schema` (needs `personalize_dictionary`) and on each `find_references` source |
| Read-only, client credentials | `snc_read_only` only | OAuth client credentials | **20** | 403 on `cmdb_ci` and the aggregates; 404 for records an ACL hides. It cannot read its own role rows, so hiding the write tools fails open (by design: ServiceNow still refuses every write) |
| Admin, read-only | `admin`, `snc_read_only` | OAuth client credentials | 13 | none for reads; every write refused |
| Admin, writer | `admin` | OAuth client credentials | 20 | none; the write smoke creates and deletes a scratch incident and an empty update set |

The counts are for 0.9.x: 13 read tools and 7 write tools (`tests/inventory.py`). `--read-only` lists 13 for every
tier.

## The smoke

`scripts/stdio_smoke.py` runs the real server over stdio with one identity. Pass the tier's tool count with
`--expect-tools`, so an unexpected fail-open is a FAIL instead of an INFO line:

```sh
# API key tier
with-secrets SERVICENOW_API_KEY=svc/<scope>/servicenow-<pdi>-apikey -- env \
  SERVICENOW_INSTANCE_URL=https://<pdi>.service-now.com SERVICENOW_AUTH_TYPE=api_key \
  uv run python scripts/stdio_smoke.py --profile readonly --expect-tools 13

# A client-credentials tier: blank username and password, so a local .env can't turn it into the password grant
with-secrets SERVICENOW_CLIENT_SECRET=svc/<scope>/servicenow-<pdi>-<tier>-client-secret -- env \
  SERVICENOW_INSTANCE_URL=https://<pdi>.service-now.com SERVICENOW_AUTH_TYPE=oauth \
  SERVICENOW_CLIENT_ID=<client id> SERVICENOW_USERNAME= SERVICENOW_PASSWORD= \
  uv run python scripts/stdio_smoke.py --profile readonly --expect-tools 20
```

Use `--profile readonly` for the three read tiers and `--profile write --expect-tools 20` for the writer. The write
profile deletes what it creates, even after a failed step; afterwards, check that no incident whose short description
contains `stdio smoke (safe to delete)` is left.

## What "0 rows" means

The same empty answer means three different things, and the server says which only where it has evidence:

| Cause | Example | What the server adds |
|---|---|---|
| **Hidden**: an ACL hides the rows | `sys_journal_field` for an identity without `admin` or `audit_viewer` | a `warning` that the entries are not assessable, not empty, and how to read the record's own journal fields |
| **Empty**: there are no such rows | `sys_audit` for a record created without auditing | nothing |
| **Nonexistent**: the record or field isn't there | a dangling reference; a field the table doesn't have | for a field: a `warning` that the condition was ignored |

A record an ACL hides answers `get_record` with 404, the same as one that doesn't exist; the error says both.
`servicenow://instance` lists in `unavailable` each value the identity can't read (build and default time zone need
`admin`).
