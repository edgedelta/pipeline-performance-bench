#!/usr/bin/env bash
# Build the static benchmark page: site/ plus data/history.json rebuilt from every
# release's data.json. Usage: tools/build_pages.sh <out-dir> [owner/repo]
set -euo pipefail

out=${1:?usage: build_pages.sh <out-dir> [owner/repo]}
repo=${2:-${GITHUB_REPOSITORY:-edgedelta/pipeline-performance-bench}}
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

rm -rf "$out"
mkdir -p "$out/data"
cp -R "$root/site/." "$out/"
rm -rf "$out/data/"*
touch "$out/.nojekyll"

# Version local asset URLs so browsers fetch the new app.jsx after each deploy.
version=$(git -C "$root" rev-parse --short HEAD 2>/dev/null || date +%s)
sed -i.bak -e "s|src=\"app.jsx\"|src=\"app.jsx?v=$version\"|" \
  -e "s|href=\"assets/benchmark.css\"|href=\"assets/benchmark.css?v=$version\"|" \
  -e "s|href=\"assets/colors_and_type.css\"|href=\"assets/colors_and_type.css?v=$version\"|" "$out/index.html"
rm "$out/index.html.bak"
echo "[]" > "$out/data/history.json"

gh release list --repo "$repo" --limit 1000 --exclude-drafts --json tagName --jq '.[].tagName' |
while read -r tag; do
  if gh release download "$tag" --repo "$repo" --pattern data.json --dir "$work/$tag" 2>/dev/null; then
    node "$root/tools/merge-history.mjs" "$out/data/history.json" "$work/$tag/data.json" "$out/data/history.json" "$tag"
  else
    echo "skipping $tag: no data.json"
  fi
done

python3 "$root/tools/fetch_otlp_reports.py" "$repo" "$out/data/otlp"
python3 "$root/tools/build_signal_pages.py" "$out"
python3 "$root/tools/build_ladder_page.py" "$out"

echo "built $out ($(du -sh "$out/data/history.json" | cut -f1) history)"
