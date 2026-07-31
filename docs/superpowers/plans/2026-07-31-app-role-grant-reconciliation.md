# App Role Grant Reconciliation — Implementation Plan

**Goal:** Make an ACL-stripped PostgreSQL restore usable by the least-privilege
`castranova_app` role before the application reads tables or serves traffic.

**Selected approach:** Keep `ensure_app_role.py` responsible only for creating
or refreshing the role. Add an idempotent reconciliation step after
`alembic upgrade head`, when every table exists, and before initial data.

**Rejected:** Replaying M026 by stamping backward can re-run later migrations.
Replacing Dokploy's backup scheduler duplicates retention, upload, and alerting.

## Task 1: Pin the recovery contract with tests

- Add `backend/tests/test_reconcile_app_role_grants.py` with a fake SQLAlchemy
  engine that captures executed SQL.
- Assert existing-table and sequence access, default privileges, the two DELETE
  exceptions, append-only ledger revocations, and `alembic_version` revocation.
- Run the test first and confirm it fails because reconciliation is absent.

## Task 2: Reconcile grants during prestart

- Add `backend/app/reconcile_app_role_grants.py` with one transaction of
  idempotent GRANT/REVOKE statements.
- Discover append-only ledgers through their `reject_ledger_mutation` trigger.
- Run it from `backend/scripts/prestart.sh` after migrations.
- Update the module contract and log completion.

## Task 3: Put the restore warning in the runbook

- Add a restore runbook warning that an ACL-stripped Dokploy archive remains
  unusable until prestart repairs grants; row counts alone are not proof.
- Make a backend pointed at `restore_test` complete login and authenticated
  `/users/me`; also verify append-only ledger UPDATE/DELETE privileges are absent.

## Verification

- Run the full backend test suite from the repository test script.
- Run Ruff and mypy for the backend.
- Review the final diff for privilege broadening and unrelated changes.
