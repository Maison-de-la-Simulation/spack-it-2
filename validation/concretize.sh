#!/bin/bash
set -e

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
    echo "Usage: concretize.sh <root-spec>" >&2
    exit 2
fi

. /opt/spack/share/spack/setup-env.sh || exit 2

VALIDATION_REPO_NAMES=$(spack repo list --names) || exit 2
if ! printf '%s\n' "$VALIDATION_REPO_NAMES" | grep -Fxq generated; then
    spack repo add /work/generated/spack_repo/generated || exit 2
fi
spack compiler find || exit 2
spack env create --without-view validation || exit 2
spack -e validation add "$1" || exit 2
spack -e validation concretize --fresh || exit 20