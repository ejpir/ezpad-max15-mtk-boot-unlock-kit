#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
shasum -a 256 -c manifests/SHA256SUMS.txt
