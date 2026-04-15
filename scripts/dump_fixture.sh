#!/bin/bash
# Dump a portable JSON fixture of the current database.
#
# Uses natural keys so FKs to content types and permissions serialize as
# ["app_label", "model"] / [codename, app_label, model] instead of integer
# PKs. This makes the fixture loadable on any machine regardless of the
# order migrations ran, since Django's auto-created permissions/content
# types provide the target PKs at load time.
#
# auth.permission and contenttypes are excluded from the dump entirely —
# post_migrate recreates them on the target, and natural-key FKs resolve
# against whatever PKs exist there.
#
# Usage:
#   ./scripts/dump_fixture.sh fixtures/large_datasets/nealseed.json

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <output-path>"
    exit 1
fi

OUTPUT="$1"

echo "Dumping to: $OUTPUT"
python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude auth.permission \
    --exclude contenttypes \
    --indent 2 \
    > "$OUTPUT"

echo "Done."
