#!/bin/sh
set -e
# Cron strips the container environment; export it to a file the jobs source.
# Single-quote wrapping preserves values containing ", $, or spaces literally.
# umask 077 keeps the credentials file readable only by root.
umask 077
printenv | sed "s/^\([A-Za-z_][A-Za-z0-9_]*\)=\(.*\)\$/export \1='\2'/" > /app/cron.env
crontab /app/deploy/cron/crontab
echo "minibini-cron: crontab installed, starting cron daemon"
exec cron -f
