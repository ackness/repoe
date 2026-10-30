#!/usr/bin/env bash
set -euo pipefail

if (( $# == 0 )); then
  set -- RePoE/schema/*.json
fi
for file in "$@"; do
  name=$(basename "$file" .json)
  uv run --locked --offline datamodel-codegen \
    --formatters ruff-format \
    --input "$file" --input-file-type jsonschema \
    --output "RePoE/model/$name.py" --output-model-type pydantic_v2.BaseModel \
    --disable-timestamp --use-double-quotes --enable-version-header
done
