#!/usr/bin/env bash
# Deploy a client static site to the shared hosting bucket.
#
#   scripts/deploy-client-site.sh <customer> <project> <local-folder>
#
# Example:
#   scripts/deploy-client-site.sh baanpong-cafe website ./baanpong-site
#   -> live at https://baanpong-cafe.zzdigitaldesign.com/website/
#
# HTML is uploaded no-cache (changes show on a refresh); other assets get a
# long cache. Uses --delete so files removed locally are removed from S3.
set -euo pipefail

BUCKET="vibecraftedsoftware-client-files"

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <customer> <project> <local-folder>"
  exit 1
fi
CUSTOMER="$1"; PROJECT="$2"; SRC="$3"
DEST="s3://$BUCKET/$CUSTOMER/$PROJECT/"

echo "Deploying $SRC -> $DEST"

# 1. sync everything (adds, updates, deletes)
aws s3 sync "$SRC" "$DEST" --delete

# 2. re-stamp HTML files as no-cache so edits appear immediately
aws s3 cp "$DEST" "$DEST" --recursive \
  --exclude "*" --include "*.html" \
  --metadata-directive REPLACE \
  --content-type "text/html; charset=utf-8" \
  --cache-control "no-cache, must-revalidate"

echo ""
echo "Done. Live at: https://$CUSTOMER.zzdigitaldesign.com/$PROJECT/"
