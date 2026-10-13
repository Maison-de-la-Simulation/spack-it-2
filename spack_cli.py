"""Locate the Spack executable used for package repository lookups."""

import os
import shutil
from pathlib import Path


class SpackNotFoundError(RuntimeError):
    """Raised when no usable Spack executable can be located."""


def spack_executable() -> str:
    """Return the Spack executable to invoke.

    Resolution order:
    1. ``SPACK_ROOT`` environment variable (root of a Spack checkout)
    2. ``spack`` found on ``PATH``
    3. a ``spack`` checkout located next to this project

    The sibling-checkout fallback keeps the tool usable in the
    development workspace and on NixOS hosts where Spack is never
    installed globally.
    """
    spack_root = os.environ.get("SPACK_ROOT")

    if spack_root:
        candidate = Path(spack_root) / "bin" / "spack"

        if not candidate.is_file():
            raise SpackNotFoundError(
                f"SPACK_ROOT is set to '{spack_root}' "
                f"but '{candidate}' does not exist"
            )

        return str(candidate)

    on_path = shutil.which("spack")

    if on_path:
        return on_path

    sibling_checkout = (
        Path(__file__).resolve().parent.parent / "spack" / "bin" / "spack"
    )

    if sibling_checkout.is_file():
        return str(sibling_checkout)

    raise SpackNotFoundError(
        "Spack executable not found: set SPACK_ROOT, add spack to PATH, "
        "or place a spack checkout next to spack-it-2"
    )
