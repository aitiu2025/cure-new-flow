#!/usr/bin/env bash
# OCR all downloaded PDFs to extracted_texts/<instrument>.txt
# Uses pdftoppm @ 250 dpi → tesseract -l eng
set -euo pipefail

CASE_DIR="/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/0523/Manatee_FERNANDEZ_fromLocalDb"
PDF_DIR="$CASE_DIR/downloads"
OUT_DIR="$CASE_DIR/extracted_texts"
mkdir -p "$OUT_DIR"

ocr_one() {
  local pdf="$1"
  local stem
  stem="$(basename "$pdf" .pdf)"
  # parse instrument: MCCCC-<instrument>-<slug>
  local instrument="${stem#MCCCC-}"
  instrument="${instrument%%-*}"
  local out="$OUT_DIR/${instrument}.txt"

  local tmp
  tmp="$(mktemp -d)"
  trap "rm -rf '$tmp'" RETURN

  # Convert to PNG @ 250 dpi
  pdftoppm -r 250 -png "$pdf" "$tmp/p" 2>/dev/null

  : > "$out"
  local n=0
  for img in "$tmp"/p-*.png; do
    [[ -f "$img" ]] || continue
    n=$((n+1))
    echo "=== PAGE $n ===" >> "$out"
    tesseract "$img" - -l eng 2>/dev/null >> "$out" || true
    echo "" >> "$out"
  done

  echo "[+] $instrument: $n page(s), $(wc -c < "$out") bytes"
}

export -f ocr_one
export OUT_DIR

# Parallel OCR (4 jobs)
ls "$PDF_DIR"/*.pdf | xargs -n1 -P4 -I{} bash -c 'ocr_one "$@"' _ {}

echo "=== OCR complete ==="
ls -la "$OUT_DIR"
