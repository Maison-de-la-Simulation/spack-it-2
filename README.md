# LangGraph for Spack

A LangGraph-based prototype for generating Spack package recipes from a source repository URL.

## Workflow Diagram

[View the workflow diagram](https://docs.google.com/drawings/d/1BurF_v5SKvKO0aYVeZHtiYBdBuWPS7Rni838SMr0aoE/edit)

## Specifications Document

[View the specifications document](https://docs.google.com/document/d/1PxDQilBn0VYcY1gO4rjn9klJaxrzWA3Mfjoo3E9CLYg/edit) 

## Overview

The tool generates Spack recipes for Python projects from a repository URL. It builds a structured recipe model using metadata from the selected source archive.

Metadata extraction and recipe rendering are deterministic. An LLM assists with optional dependency group decisions. Generated recipes are checked with Spack audit, concretization and installation in a container.

## Current workflow

The prototype currently:

- validates the URL, clones the repository and inspects the project;
- extracts initial metadata from the repository;
- selects a PyPI source distribution or repository-tag archive and reads its metadata;
- derives a structured recipe model, with LLM assistance when needed;
- asks before replacing existing package output;
- recursively generates missing dependency recipes within the requested depth;
- renders `package.py` from the recipe model;
- runs Spack audit, concretization and installation in a validation container;
- removes the validation container and saves the main package's results.

## Project structure

- `graph.py` — defines the LangGraph workflow and transitions.
- `nodes/` — contains the workflow node implementations, split by stage.
- `spack_cli.py` — manages validation containers and runs Spack commands.
- `validation/` — contains the Dockerfile and scripts for audit, concretization and installation.
- `state.py` — defines the shared state used by the graph.
- `tool.py` — provides the command-line entry point.
- `.gitignore` — excludes generated files, virtual environments, caches, and local workspace files.

## Setup

Requirements: Python 3.12 or newer, Git, and a running Docker or Podman runtime.

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The tool selects Docker if its command is available; otherwise it selects Podman. Build the validation image with the selected runtime.

For Docker:

```bash
docker build -t localhost/spack-it-validation:1.2.2 validation
```

For Podman:

```bash
podman build -t localhost/spack-it-validation:1.2.2 validation
```

Rebuild the image after changing its Dockerfile or validation scripts.

For LLM assistance:

- `mdls` uses the configured MDLS server, which must be reachable when needed.
- `open-router` requires `OPENROUTER_API_KEY` in the environment.

## Usage

Run commands from the repository root with the virtual environment activated.

Simple package example:

```bash
python tool.py --select-llm mdls -L 1 https://github.com/pallets/click
```

Recursive dependency example:

```bash
python tool.py --select-llm open-router -L 1 https://github.com/DanCardin/cappa
```

`--select-llm` defaults to `mdls`. `-L` sets the maximum recursive dependency depth and defaults to `0`. `-L 1` allows the tool to generate recipes for missing direct dependencies. Use `--verbose` to see each workflow step in the terminal.

The tool prepares the generated Spack repository and runs validation automatically. Installation can take several minutes.

If Spack audit fails, the selected LLM can try up to two repairs. Each repair can change only one dependency's version constraint. The tool saves the corrected recipe only after it passes validation.

A successful run exits with code `0`. Failure or cancellation returns a non-zero exit code.

## Generated files

Package names use underscores in output paths: `py-cappa` becomes `py_cappa`.

A successful Cappa run with a generated TypeLens dependency produces:

```text
outputs/recipes/py_cappa/package.py
outputs/recipes/py_type_lens/package.py
outputs/metadata/py_cappa/metadata.json
```

The main package's `metadata.json` records source details, the recipe model, node history, each validation attempt, and the number of repairs tried. Generated dependencies receive their own `package.py` and are included in the parent validation workflow.

If either output file already exists for a package:

| Reply | Result |
| --- | --- |
| `y` | Clears that package's previous `package.py` and `metadata.json`, then continues. |
| Enter or any other reply | Cancels the run and preserves that package's existing files. |

Cancelling a dependency also stops the parent run. Files cleared after an earlier approval are not restored.

Cancelled runs do not write final metadata. If the main run fails before output preparation, its existing output is preserved.

The `outputs/` directory is excluded from Git.

## Current limitations

- The workflow targets Python projects with a `[project]` table in `pyproject.toml`.
- Early dependency checks look up package names; version conflicts are detected later by Spack validation.
- Some valid Python version constraints are unsupported and require human review.
- Concretization and installation cover the default variant configuration.
- The displayed quality score is currently a fixed 90% placeholder.
- Generated recipes may still require manual changes.

## Planned development

- recipe quality scoring;
- runtime checks and broader optional-variant testing;
- support for repairing more types of validation errors;
- support for additional project types and build systems.

## Project status

Prototype under active development at Maison de la Simulation, CEA Paris-Saclay.