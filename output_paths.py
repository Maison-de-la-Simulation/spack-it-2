from pathlib import Path


def recipe_output_path(package_name: str) -> Path:
    return Path("outputs/recipes") / package_name.replace("-", "_") / "package.py"


def metadata_output_path(package_name: str) -> Path:
    return Path("outputs/metadata") / package_name.replace("-", "_") / "metadata.json"
