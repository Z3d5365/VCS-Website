#!/usr/bin/env bash
# Deploy websites.vibecraftedsoftware.com.
#
#   scripts/deploy.sh
#
# Steps, in order:
#   1. rebuild the Thai page from the English source + TH dictionary
#   2. rebuild the Pagefind search index over every public page
#   3. upload the public files (an explicit allowlist — never `sync .`, which
#      would ship docs/, build/, backend/, CLAUDE.md and the rest of the repo)
#   4. sync the /pagefind/ bundle, deleting index files from older builds
#   5. invalidate CloudFront
#
# HTML is uploaded no-cache so edits are live after the invalidation plus a
# refresh. The Pagefind index files are content-hashed and immutable, so they
# get a long cache; only the two entry files it always re-reads are no-cache.
set -euo pipefail

BUCKET="websites.vibecraftedsoftware.com"
DIST_ID="EBJNRLIZ8CTTY"
PAGEFIND_VERSION="1.3.0"

# Pages that carry data-pagefind-body and should be searchable. The portal and
# the search pages themselves are deliberately absent.
INDEX_GLOB="{index.html,services/*/index.html,th/index.html,th/services/*/index.html}"

NOCACHE="no-cache, must-revalidate"
IMMUTABLE="public, max-age=31536000, immutable"
HTML_TYPE="text/html; charset=utf-8"

cd "$(dirname "$0")/.."

HTML_FILES=(
  index.html
  th/index.html
  search/index.html
  th/search/index.html
  services/hosting/index.html
  services/local-seo/index.html
  services/logo-brand/index.html
  services/web-design/index.html
  th/services/hosting/index.html
  th/services/local-seo/index.html
  th/services/logo-brand/index.html
  th/services/web-design/index.html
  portal/index.html
  portal/admin/index.html
)

echo "==> 1/5  Rebuilding the Thai page"
node build/build-th.js

echo ""
echo "==> 2/5  Indexing every public page with Pagefind"
rm -rf pagefind
npx -y "pagefind@$PAGEFIND_VERSION" --site . --glob "$INDEX_GLOB"

if [ ! -f pagefind/pagefind-entry.json ]; then
  echo "Pagefind produced no index — aborting before we ship a broken search." >&2
  exit 1
fi

echo ""
echo "==> 3/5  Uploading pages and assets"
for f in "${HTML_FILES[@]}"; do
  aws s3 cp "$f" "s3://$BUCKET/$f" --cache-control "$NOCACHE" --content-type "$HTML_TYPE"
done
aws s3 cp assets/service.css "s3://$BUCKET/assets/service.css" --cache-control "$NOCACHE" --content-type "text/css; charset=utf-8"
aws s3 cp assets/search.js   "s3://$BUCKET/assets/search.js"   --cache-control "$NOCACHE" --content-type "text/javascript; charset=utf-8"
aws s3 cp robots.txt         "s3://$BUCKET/robots.txt"         --cache-control "$NOCACHE" --content-type "text/plain; charset=utf-8"
aws s3 cp sitemap.xml        "s3://$BUCKET/sitemap.xml"        --cache-control "$NOCACHE" --content-type "application/xml"

echo ""
echo "==> 4/5  Syncing the search index"
# --delete clears the hashed index files left behind by the previous build.
aws s3 sync pagefind/ "s3://$BUCKET/pagefind/" --delete --cache-control "$IMMUTABLE"
# These two are read on every search and must never be a stale cached copy.
for f in pagefind-entry.json pagefind.js; do
  case "$f" in
    *.json) ct="application/json" ;;
    *)      ct="text/javascript; charset=utf-8" ;;
  esac
  aws s3 cp "s3://$BUCKET/pagefind/$f" "s3://$BUCKET/pagefind/$f" \
    --metadata-directive REPLACE --content-type "$ct" --cache-control "$NOCACHE"
done

echo ""
echo "==> 5/5  Invalidating CloudFront"
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" \
  --query 'Invalidation.{Id:Id,Status:Status}' --output table

echo ""
echo "Done. https://websites.vibecraftedsoftware.com/  ·  search: /search/ and /th/search/"
