import shutil
import subprocess

SPACK_IMAGE = "docker.io/spack/ubuntu-noble:1.2.2"


def run_spack_info(package_name: str) -> subprocess.CompletedProcess[str]:
    runtime = shutil.which("docker") or shutil.which("podman")

    if runtime is None:
        raise FileNotFoundError(
            "Docker or Podman is required for Spack lookups."
        )

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