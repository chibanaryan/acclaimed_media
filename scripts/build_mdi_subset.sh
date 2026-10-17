#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FONT_PATH="$ROOT_DIR/games/static/games/fonts/materialdesignicons-webfont.woff2"
MAPPING_FILES=(
  "$ROOT_DIR/games/templates/base.html"
  "$ROOT_DIR/games/static/games/css/mdi-subset.css"
)

# Subset from the full upstream font, never from FONT_PATH itself: subsetting
# the existing subset in place can only ever drop glyphs, so a newly
# referenced icon was silently omitted and rendered as a blank box. The
# version is pinned so a rebuild is reproducible and matches the codepoints
# in the mapping files.
MDI_VERSION="7.4.47"
MDI_FONT_URL="https://cdn.jsdelivr.net/npm/@mdi/font@${MDI_VERSION}/fonts/materialdesignicons-webfont.woff2"

if ! command -v pyftsubset >/dev/null 2>&1; then
  echo "pyftsubset is required (pip install fonttools brotli zopfli)"
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to fetch the full MDI font"
  exit 1
fi

if [[ ! -f "$FONT_PATH" ]]; then
  echo "Font not found: $FONT_PATH"
  exit 1
fi

tmp_codes="$(mktemp)"
tmp_unicodes="$(mktemp)"
tmp_output="$(mktemp "${TMPDIR:-/tmp}/mdi-subset.XXXXXX")"
tmp_full_font="$(mktemp "${TMPDIR:-/tmp}/mdi-full.XXXXXX")"
trap 'rm -f "$tmp_codes" "$tmp_unicodes" "$tmp_output" "$tmp_full_font"' EXIT

for mapping_file in "${MAPPING_FILES[@]}"; do
  if [[ -f "$mapping_file" ]]; then
    grep -ohE '\\F[0-9A-Fa-f]+' "$mapping_file" >> "$tmp_codes" || true
  fi
done

if [[ ! -s "$tmp_codes" ]]; then
  echo "No icon codepoints found in mapping files."
  exit 1
fi

tr 'a-f' 'A-F' < "$tmp_codes" | sort -u | sed 's/^\\//' | awk '{print "U+"$0}' > "$tmp_unicodes"
unicode_list="$(paste -sd, "$tmp_unicodes")"

if [[ -z "$unicode_list" ]]; then
  echo "Computed unicode list is empty."
  exit 1
fi

original_size="$(wc -c < "$FONT_PATH" | tr -d ' ')"
codepoint_count="$(wc -l < "$tmp_unicodes" | tr -d ' ')"

echo "Fetching full MDI font v${MDI_VERSION}..."
if ! curl -fsSL "$MDI_FONT_URL" -o "$tmp_full_font"; then
  echo "Could not download the full MDI font from $MDI_FONT_URL"
  exit 1
fi

pyftsubset "$tmp_full_font" \
  --unicodes="$unicode_list" \
  --flavor=woff2 \
  --layout-features='*' \
  --desubroutinize \
  --output-file="$tmp_output"

mv "$tmp_output" "$FONT_PATH"
new_size="$(wc -c < "$FONT_PATH" | tr -d ' ')"

echo "Subset complete: $FONT_PATH"
echo "Codepoints kept: $codepoint_count"
echo "Size: $original_size -> $new_size bytes"
