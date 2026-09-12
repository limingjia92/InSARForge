# Configuration

InSARForge configuration files use schema version 1. Validate a file before
running any later configuration-only command:

```text
insarforge config validate examples/config/pair_manual_minimal.yaml
insarforge config resolve examples/config/pair_manual_minimal.yaml
```

`validate` checks syntax, schema fields, ranges, cross-field intent, and safe
paths without writing files. `resolve` prints to stdout by default; with
`--write-dir` it exclusively creates `requested_config.yaml`,
`resolved_config.yaml`, and `config_resolution.json`. Both commands are offline and do not search for
products, credentials, or backend executables.

Use `--set path=value` for a temporary typed override, for example:

```text
insarforge config resolve config.yaml --set data.search.longitude=12.5
```

The six public examples under `examples/config/` show minimal and fuller Pair,
event Pair, and Stack configurations. Copy one into a project and change its
relative or absolute `project.work_dir` and active fields for that project.

The configuration surface is intentionally limited to the frozen schema. The
17 supported legacy options are `mode`, `data_source`, `lon`, `lat`,
`event_date`, `reference_date`, `secondary_date`, `start_date`, `end_date`,
`num_proc`, `platform`, `rel_orbit`, `search_dlonlat`, `roi_dlonlat`,
`dlonlat`, `zip_check_backend`, and `step`. Dates use eight digits in legacy
input and ISO dates in YAML; platform aliases and provider aliases are
normalized, while relative orbit is a positive integer or null.

Search coordinates use `data.search`; `search_dlonlat` and `dlonlat` select
the search width, while `roi_dlonlat` selects the ROI width. Supplying both
search aliases is a conflict. A null ROI inherits the search width, and ROI
zero is valid. Pair selection is manual when reference and secondary dates
are supplied together, or event when an event date is supplied. `config`
maps to `prepare` and `post` maps to `postprocess`; `clean`, multiple commands,
and unsupported shell syntax are rejected.

`translate-legacy` has a separate two-file contract (`insarforge.yaml` and
`legacy_translation.json`); its relative write directory is based on the
command file. Relative YAML paths are based on the YAML file's directory.
Configuration commands do not execute SAR processing. Notices and errors use stable codes and never
echo secrets. The translator does not infer a legacy software version or
reconstruct unavailable historical bytes; all operations are offline.
