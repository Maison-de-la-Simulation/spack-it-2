#!/bin/bash
set -e

if [ "$#" -ne 0 ]; then
    echo "Usage: install.sh" >&2
    exit 2
fi

. /opt/spack/share/spack/setup-env.sh || exit 2

VALIDATION_ENV_DIR=$(spack location -e validation) || exit 2
if [ ! -f "$VALIDATION_ENV_DIR/spack.lock" ]; then
    echo "Missing spack.lock; run concretization first." >&2
    exit 2
fi

spack -e validation install --fail-fast || exit 30