# Legacy CLI migration

Extract one old `autoInSAR.py` command into a UTF-8 text file, then translate
it without executing the old program:

```text
insarforge config translate-legacy pair.command.txt \
  --legacy-cwd /srv/insar/pair \
  --write-dir generated-pair
```

The command writes exactly `insarforge.yaml` and
`legacy_translation.json` into a new `generated-pair` directory. A relative
`--write-dir` is based on the command file's parent directory; the legacy work
directory is recorded in the generated configuration and is never inspected
or created. Without `--write-dir`, compact YAML is printed to stdout and the
complete migration record remains available through the translation API.

The accepted old options, aliases, date rules, and rejected shell syntax are
finite and deliberate. The supported single-command subset contains the 17
options documented in `docs/configuration.md`; dates are `YYYYMMDD`, platform
and provider aliases are accepted, and search/ROI aliases have conflict
rules. `--step config` maps to `prepare` and `--step post` maps to
`postprocess`; `--step all` is accepted (and excludes `clean`); `clean` alone is rejected. After migration, run
the normal configuration commands:

```text
insarforge config validate generated-pair/insarforge.yaml
insarforge config resolve generated-pair/insarforge.yaml
```

Translation is configuration-only. It does not run `autoInSAR.py`, access
network services, read credentials, inspect SAR products, or import ISCE/GAMMA.
The output record stores the source path and the SHA-256 of the original bytes,
explicit option order, field mappings, synthesized fields, defaults and notices.
It does not store the original command text. It records C1's two-file
configuration output; no three-file processing output is produced. Errors are
stable safe codes such as `CONFIG_SECRET`, `CONFIG_PATH`, and
`LEGACY_TRANSLATION`, with secret values omitted. The supported phase and
quicklook parameters are represented in YAML, but execution, product search,
provider access, and historical command/version reconstruction remain outside
this configuration-only release.
