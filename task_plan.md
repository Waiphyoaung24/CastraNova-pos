# CastraNova POS Production Deployment Plan

## Decision

- Deploy the `production` branch as a fresh installation.
- Use `compose.dokploy.production.yml` without published host ports.
- Route `pos.castranova.cloud` to `frontend:80` and
  `api.castranova.cloud` to `backend:8000` through Dokploy Traefik.
- Route `*.castranova.cloud` through Cloudflare Tunnel to
  `http://dokploy-traefik:80`.
- Store daily PostgreSQL and Dokploy backups in a private Cloudflare R2 bucket.

## Deployment Gates

1. Validate Compose and confirm no host ports are published.
2. Merge this infrastructure change into `production`.
3. Configure Dokploy environment values without committing secrets.
4. Configure Cloudflare wildcard DNS/tunnel routing and Dokploy domains with
   HTTPS disabled internally.
5. Obtain explicit approval immediately before the production Deploy action.
6. Verify database health, migrations, backend health, frontend loading, and
   login before enabling AutoDeploy.

## Backup Gates

1. Create a private R2 bucket and bucket-scoped API token.
2. Add and test the R2 S3 destination in Dokploy.
3. Schedule PostgreSQL logical backups daily at 02:15 Asia/Bangkok after
   confirming the scheduler timezone; retain 14 copies where supported.
4. Schedule a separate Dokploy system backup.
5. Trigger an immediate backup and verify the object in R2.
6. Rehearse a restore into a disposable database or project and document the
   result before treating the backup system as operational.

## Rollback

- Stop the new Compose service or disable its domains before cutover.
- Redeploy the previous known-good production commit for application rollback.
- Never delete the PostgreSQL named volume during an application rollback.
