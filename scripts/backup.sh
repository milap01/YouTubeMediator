#!/bin/sh
set -eu

stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p backups

docker compose -f infra/docker-compose.yml exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "backups/postgres-$stamp.dump"

docker compose -f infra/docker-compose.yml exec -T backend \
  python -c 'import sys,tarfile; archive=tarfile.open(fileobj=sys.stdout.buffer,mode="w|gz"); archive.add("/app/media",arcname="media"); archive.close()' \
  > "backups/media-$stamp.tar.gz"

printf 'Created backups/postgres-%s.dump and backups/media-%s.tar.gz\n' "$stamp" "$stamp"
