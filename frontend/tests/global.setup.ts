import { execSync } from "node:child_process"
import { test as setup } from "@playwright/test"

// Per-run DB reset (hardening spec §5): truncate all app tables, then re-run
// prestart (alembic no-op + init_db reseeds superuser, locations, settings —
// see backend/app/core/db.py). Runs BEFORE auth.setup.ts via project
// dependencies. Host-coupled to the compose dev stack by design — this suite
// only ever runs against it (see the e2e-shared-dev-db memory notes).
setup.setTimeout(120_000)

setup("reset dev database", () => {
  if (process.env.E2E_SKIP_DB_RESET === "1") {
    console.log("E2E_SKIP_DB_RESET=1 — skipping DB reset")
    return
  }
  // import.meta.dirname (Node >=20.11): this file is ESM ("type": "module"),
  // so CommonJS __dirname is not defined here.
  const repoRoot = `${import.meta.dirname}/../..`
  const truncate = `
    DO $$ DECLARE names text;
    BEGIN
      SELECT string_agg(quote_ident(tablename), ', ') INTO names
      FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version';
      IF names IS NOT NULL THEN
        EXECUTE 'TRUNCATE TABLE ' || names || ' RESTART IDENTITY CASCADE';
      END IF;
    END $$;`
  // SQL goes via stdin: interpolating it into the shell command would let
  // sh expand the plpgsql `$$` quoting to its own PID.
  // timeout on each child: Playwright's test timeout can't preempt a blocked
  // execSync, so the budget must be enforced by Node killing the child.
  execSync(
    "docker compose exec -T db psql -U postgres -d app -v ON_ERROR_STOP=1 -f -",
    {
      cwd: repoRoot,
      input: truncate,
      stdio: ["pipe", "inherit", "inherit"],
      timeout: 30_000,
    },
  )
  // `run --rm` blocks until prestart finishes (deterministic, no sleeps).
  execSync("docker compose run --rm prestart", {
    cwd: repoRoot,
    stdio: "inherit",
    timeout: 120_000,
  })
})
