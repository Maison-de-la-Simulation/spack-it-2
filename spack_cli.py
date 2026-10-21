import shutil
import uuid
import subprocess
from pathlib import Path

SPACK_IMAGE = "docker.io/spack/ubuntu-noble:1.2.2"
VALIDATION_IMAGE = "localhost/spack-it-validation:1.2.2"


def remove_validation_container(container_name: str) -> None:
    try:
        result = subprocess.run(
            [container_runtime(), "rm", "--force", container_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("Validation container removal timed out.") from error

    if result.returncode != 0:
        raise OSError(
            result.stderr.strip() or result.stdout.strip()
            or f"Could not remove validation container {container_name}."
        )


def cleanup_failed_start(container_name: str) -> None:
    try:
        remove_validation_container(container_name)
    except OSError as error:
        print("Could not clean up failed container startup:", error)


def start_validation_container(generated_dir: Path) -> str:
    generated_dir = generated_dir.resolve(strict=True)
    repo_file = generated_dir / "spack_repo" / "generated" / "repo.yaml"
    if not repo_file.is_file():
        raise FileNotFoundError(f"Missing generated repository: {repo_file}")

    container_name = f"spack-it-validation-{uuid.uuid4().hex}"
    command = [
        container_runtime(), "run", "-d", "--pull=never",
        "--name", container_name,
        "-v", f"{generated_dir}:/work/generated:ro",
        VALIDATION_IMAGE, "-c", "exec sleep infinity",
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        cleanup_failed_start(container_name)
        raise TimeoutError("Validation container startup timed out.") from error
    except KeyboardInterrupt:
        cleanup_failed_start(container_name)
        raise

    if result.returncode != 0:
            message = result.stderr.strip()

            if not message:
                message = result.stdout.strip()

            if not message:
                message = "Could not start validation container."

            cleanup_failed_start(container_name)
            raise OSError(message)

    return container_name


def container_runtime() -> str:
    runtime = shutil.which("docker") or shutil.which("podman")

    if runtime is None:
        raise FileNotFoundError(
            "Docker or Podman is required for Spack commands."
        )

    return runtime


def run_spack_info(package_name: str) -> subprocess.CompletedProcess[str]:

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


def run_validation_step(
    container_name: str,
    step: str,
    arguments: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a validation script and display its output as it arrives."""
    if step not in {"audit", "concretize", "install"}:
        raise ValueError(f"Unknown validation step: {step}")

    runtime = container_runtime()
    command = [
        runtime,
        "exec",
        "-e",
        "PYTHONUNBUFFERED=1",
        container_name,
        "/bin/bash",
        f"/opt/validation/{step}.sh",
        *(arguments or []),
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output = []

    try:
        for line in process.stdout:
            output.append(line)
            print(line, end="", flush=True)

        returncode = process.wait()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

        process.stdout.close()

    log = "".join(output)
    if returncode in (125, 126, 127):
        raise OSError(log.strip() or "The validation script could not run.")

    return subprocess.CompletedProcess(command, returncode, log, "")
