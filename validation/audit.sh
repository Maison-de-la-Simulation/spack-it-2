#!/bin/bash
set -e

if [ "$#" -eq 0 ]; then
    echo "Usage: audit.sh <package> [package ...]" >&2
    exit 2
fi

. /opt/spack/share/spack/setup-env.sh || exit 2

spack repo add /work/generated/spack_repo/generated || exit 2
spack audit packages "$@" || exit 10