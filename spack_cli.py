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
            command, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise OSError(
                result.stderr.strip() or result.stdout.strip()
                or "Could not start the validation container."
            )
    except BaseException as error:
        try:
            remove_validation_container(container_name)
        except (OSError, subprocess.SubprocessError):
            pass

        if isinstance(error, subprocess.TimeoutExpired):
            raise TimeoutError("Validation container startup timed out.") from error
        raise

    return container_name


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
        assert process.stdout is not None
        for line in process.stdout:
            output.append(line)
            print(line, end="", flush=True)

        returncode = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        try:
            subprocess.run(
                [runtime, "stop", "--time", "0", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()

    log = "".join(output)
    if returncode in (125, 126, 127):
        raise OSError(log.strip() or "The validation script could not run.")

    return subprocess.CompletedProcess(command, returncode, log, "")
