# LangGraph for Spack

A LangGraph-based prototype for generating Spack package recipes from a source repository URL.

## Overview

The project analyses a software repository, extracts its package metadata, resolves its source archive, and generates an initial Spack `package.py` recipe.

The current implementation is deterministic and rule-based. LLM-assisted recipe modelling, validation, and repair will be added in later development phases.

## Current workflow

The prototype currently:

- clones the provided source repository;
- inspects the repository files;
- detects the project type and build system;
- extracts package metadata;
- identifies package dependencies;
- resolves a source archive;
- generates a Spack package recipe;
- writes the generated files to the `outputs/` directory.

## Project structure

- `graph.py` — defines the LangGraph workflow and transitions.
- `nodes.py` — contains the workflow node implementations.
- `state.py` — defines the shared state used by the graph.
- `tool.py` — provides the command-line entry point.
- `.gitignore` — excludes generated files, virtual environments, caches, and local workspace files.

## Usage

Activate the Python virtual environment:

```bash
source .venv/bin/activate
```

Run the tool with a repository URL:

```bash
python tool.py <repository-url>
```

Example:

```bash
python tool.py https://github.com/deisa-project/deisa-dask
```

## Generated files

Generated files are written under:

```text
outputs/<spack-package-name>/
```

The output currently includes:

```text
package.py
metadata.json
```

The `outputs/` directory is intentionally excluded from Git because it contains generated files.

## Current limitations

- The workflow currently focuses on Python projects.
- Recipe generation is rule-based.
- Generated recipes may still require human review.
- Advanced validation against Spack is not yet fully integrated.
- LLM-assisted reasoning and confidence-based decisions are not yet implemented.

## Planned development

Future work includes:

- structured recipe modelling;
- LLM-assisted metadata interpretation;
- confidence scoring and provenance tracking;
- automatic Spack validation;
- recipe repair based on validation errors;
- explicit human-review branches;
- support for additional project types and build systems.

## Project status

Prototype under active development at Maison de la Simulation, CEA Paris-Saclay.