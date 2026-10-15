import shutil
import subprocess
from pathlib import Path

SPACK_IMAGE = "docker.io/spack/ubuntu-noble:1.2.2"
VALIDATION_IMAGE = "localhost/spack-it-validation:1.2.2"

def container_runtime() -> str:
    runtime = shutil.which("docker") or shutil.which("podman")

    if runtime is None:
        raise FileNotFoundError(
            "Docker or Podman is required for Spack commands."
        )

    return runtime


def run_spack_info(package_name: str) -> subprocess.CompletedProcess[str]:
    runtime = shutil.which("docker") or shutil.which("podman")

    runtime = container_runtime()

    try:
        result = subprocess.run(
            [
                runtime,
                "run",
                "--rm",
                SPACK_IMAGE,
                "info",
                f"builtin.{package_name}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(
            "Spack lookup timed out after 120 seconds."
        ) from error

    if result.returncode in (125, 126, 127):
        raise OSError(
            result.stderr.strip() or "The Spack container could not run."
        )

    return result


def run_spack_audit(
    generated_dir: Path,
    packages: list[str],
) -> subprocess.CompletedProcess[str]:
    command = [
        container_runtime(),
        "run",
        "--rm",
        "--pull=never",
        "-v",
        f"{generated_dir.resolve()}:/work/generated:ro",
        VALIDATION_IMAGE,
        "/opt/validation/audit.sh",
        *[f"generated.{package}" for package in packages],
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(
            "Spack audit timed out after 120 seconds."
        ) from error

    if result.returncode in (125, 126, 127):
        raise OSError(
            result.stderr.strip() or "The audit container could not run."
        )

    return result
