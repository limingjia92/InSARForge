# InSARForge

**InSARForge** is a research-oriented framework for building reproducible
multi-mission and multi-backend InSAR processing workflows.

> **Status: Configuration-only development**
>
> The schema, configuration validation/resolution, and legacy command translation
> are implemented. SAR processing execution is not implemented.

## Motivation

InSARForge is being developed to provide a unified and extensible workflow
for two major research scenarios:

1. rapid pair-based InSAR processing for earthquakes and other high-deformation events;
2. long-term stack preparation and time-series analysis for regional deformation studies.

The framework is designed to separate satellite missions, data providers,
InSAR processors, correction methods, and time-series analyzers so that
different scientific processing strategies can be configured and compared
within a reproducible workflow.

## Planned architecture

InSARForge is planned around the following major components:

- Mission
- Data Provider
- Processor Backend
- Product
- Correction Backend
- Analyzer Backend
- Quality Control
- Provenance and workflow state management

Planned processing backends include ISCE2, ISCE3, GAMMA, and GMTSAR.

Planned time-series analyzers include StaMPS-HPC and MintPy.

Planned correction interfaces will support processor-native, external, and
custom tropospheric and ionospheric correction methods.

## Relationship to autoInSAR

InSARForge originates from experience gained during the development and use
of **autoInSAR**, a Sentinel-1 / ISCE2 automated workflow for pair processing
and time-series stack preparation.

The original autoInSAR repository is retained as an independent stable/legacy
project for compatibility and reproducibility.

InSARForge is a new project with a redesigned architecture and does not replace
the historical autoInSAR software versions.

## Relationship to StaMPS-HPC

**StaMPS-HPC** remains an independent project.

InSARForge will provide interfaces for preparing compatible time-series
products and invoking or assisting downstream StaMPS-HPC workflows.

## Development status

Current development phase:

Current work focuses on stable schema and configuration behavior.

Development install: `pip install -e '.[dev]'`. See `docs/configuration.md` and `docs/legacy_cli_migration.md`.

## License

InSARForge is licensed under the MIT License.

Third-party software and processing backends retain their respective licenses.

## Author

Mingjia Li
## Configuration
See [docs/configuration.md](docs/configuration.md) and [docs/legacy_cli_migration.md](docs/legacy_cli_migration.md).
