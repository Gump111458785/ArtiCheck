#!/usr/bin/env bash
# Run the USER-INSTALLED upstream in a separate environment; no vendored source.
set -euo pipefail
: "${UPSTREAM_DIR:?Set UPSTREAM_DIR to your separately installed baseline checkout}"
: "${BASELINE_PYTHON:?Set BASELINE_PYTHON to the baseline environment Python executable}"
if [ "$#" -lt 2 ]; then
  echo "Usage: bash scripts/run_upstream.sh /absolute/paper.pdf /absolute/report.md [extra CLI options]"
  exit 2
fi
baseline_pdf=$1
baseline_output=$2
shift 2
case "$baseline_pdf:$baseline_output" in
  /*:/*) ;;
  *) echo "Use absolute PDF and output paths"; exit 2 ;;
esac
case "$baseline_output" in
  *.md) ;;
  *) echo "Baseline output must end in .md"; exit 2 ;;
esac
baseline_commit=$(git -C "$UPSTREAM_DIR" rev-parse HEAD)
echo "Baseline commit: $baseline_commit"
echo "Upstream uses local subprocess execution by default. Configure its --vm-host for untrusted artifacts."
cd "$UPSTREAM_DIR"
"$BASELINE_PYTHON" repro_cli.py run --pdf "$baseline_pdf" --mode reproduce-deep \
  --output "$baseline_output" "$@"
"$BASELINE_PYTHON" -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["articheck_upstream_commit"]=sys.argv[2]; open(p,"w").write(json.dumps(d,indent=2))' \
  "${baseline_output%.*}.json" "$baseline_commit"
