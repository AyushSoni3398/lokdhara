# The backup container (docs/OBSERVABILITY_AND_BACKUPS.md §3). The PostgreSQL 18 image gives
# a pg_dump that matches the server; age encrypts, rclone copies off-site.
FROM postgres:18

RUN apt-get update \
    && apt-get install -y --no-install-recommends age rclone ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY backup.sh restore.sh schedule.sh /usr/local/bin/

# Not root: the image's postgres user owns the local backup folder.
RUN mkdir -p /backups && chown postgres /backups
USER postgres
ENTRYPOINT []
CMD ["/usr/local/bin/schedule.sh"]
