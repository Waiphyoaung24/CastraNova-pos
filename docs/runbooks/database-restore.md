# Database Restore Runbook

> **WARNING:** Dokploy PostgreSQL archives omit database privileges. Restored
> row counts can look correct while `castranova_app` cannot query any table.
> Always run the complete backend prestart sequence against the restored
> database before testing or serving it.

Restore into a scratch database first. Never overwrite `app` during a drill.

```bash
docker exec -i <db-container> psql -U postgres -c 'CREATE DATABASE restore_test'
gunzip -c backup.sql.gz | docker exec -i <db-container> pg_restore -U postgres -d restore_test --no-owner
```

Point a one-off backend container at `restore_test`, using the production app
role settings, and run the same prestart script used by deployment:

```bash
docker compose -f compose.dokploy.yml run --rm -e POSTGRES_DB=restore_test prestart
```

Start that backend against `restore_test`. Complete a real login and an
authenticated `GET /api/v1/users/me`. Row counts are secondary checks only.

Verify every table protected by the append-only trigger still denies UPDATE
and DELETE to the app role:

```sql
SELECT table_rel.relname,
       has_table_privilege('castranova_app', table_rel.oid, 'UPDATE') AS can_update,
       has_table_privilege('castranova_app', table_rel.oid, 'DELETE') AS can_delete
FROM pg_trigger AS trg
JOIN pg_class AS table_rel ON table_rel.oid = trg.tgrelid
JOIN pg_namespace AS table_ns ON table_ns.oid = table_rel.relnamespace
JOIN pg_proc AS trigger_fn ON trigger_fn.oid = trg.tgfoid
JOIN pg_namespace AS fn_ns ON fn_ns.oid = trigger_fn.pronamespace
WHERE NOT trg.tgisinternal
  AND table_ns.nspname = 'public'
  AND fn_ns.nspname = 'public'
  AND trigger_fn.proname = 'reject_ledger_mutation'
ORDER BY table_rel.relname;
```

Every `can_update` and `can_delete` value must be `false`. Record the artifact
timestamp and verification result, then remove only the scratch database:

```bash
docker exec -i <db-container> psql -U postgres -c 'DROP DATABASE restore_test'
```
