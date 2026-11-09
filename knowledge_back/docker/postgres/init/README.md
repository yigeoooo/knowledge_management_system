# Legacy PostgreSQL container mount

Keep this directory for existing containers that bind it to
`/docker-entrypoint-initdb.d`. Removing it prevents those containers from starting,
even when their database volume is already initialized.

This directory intentionally contains no initialization SQL. New installations
use the repository-root `init.sql` as described in `install.md`; never import it
again into an existing business database. New containers do not need this bind
mount.
