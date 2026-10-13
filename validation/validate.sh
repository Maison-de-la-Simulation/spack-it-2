#!/bin/bash
# Validation entrypoint running inside the pinned Spack image.
#
# Usage: validate.sh <root-spec> [max-tier]
#
# The generated repository is expected at /work/generated/spack_repo/generated
# (see nodes/validation.py for the staging layout).
#
# Exit codes:
#   0  all requested tiers passed
#   2  sandbox setup or usage failure
#   10 spack audit packages reported issues
#   20 spack concretize failed

set -eu

GENERATED_REPO=/work/generated/spack_repo/generated
SPEC="${1:-}"
MAX_TIER="${2:-concretize}"

if [ -z "$SPEC" ] || [ "$MAX_TIER" != "audit" ] && [ "$MAX_TIER" != "concretize" ]; then
    echo "usage: validate.sh <root-spec> [audit|concretize]" >&2
    exit 2
fi

. /opt/spack/share/spack/setup-env.sh

if ! spack repo add "$GENERATED_REPO" > /dev/null; then
    echo "failed to add generated repository $GENERATED_REPO" >&2
    exit 2
fi

audit_packages() {
    local specs=() pkg_dir

    for pkg_dir in "$GENERATED_REPO"/packages/*/; do
        [ -d "$pkg_dir" ] || continue
        specs+=("generated.$(basename "$pkg_dir" | tr '_' '-')")
    done

    if [ ${#specs[@]} -eq 0 ]; then
        echo "no generated packages found to audit" >&2
        return 2
    fi

    spack audit packages "${specs[@]}"
}

concretize_spec() {
    local env=validation

    spack env create --without-view "$env" > /dev/null &&
        spack -e "$env" add "$SPEC" > /dev/null &&
        spack -e "$env" concretize --fresh
}

echo "=== tier: spack audit packages ==="
if ! audit_packages; then
    rc=$?
    if [ "$rc" -eq 2 ]; then
        exit 2
    fi
    echo "validation failed: spack audit packages reported issues" >&2
    exit 10
fi

if [ "$MAX_TIER" = "audit" ]; then
    exit 0
fi

echo "=== tier: spack concretize ==="
if ! concretize_spec; then
    echo "validation failed: concretization failed" >&2
    exit 20
fi

exit 0
