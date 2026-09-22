# Release validation — v0.1.0

Validated on 2026-09-08, Linux x86_64. The dedicated `prowet` conda
controller environment uses Python 3.11.16, gemmi 0.7.5, h5py 3.16.0,
numpy 2.4.6 and openpyxl 3.1.5. Exact conda and pip runtime versions are
recorded in `envs/conda-linux-64.lock` and `envs/controller-pip.txt`.

## Automated checks

All 14 unittest cases pass in the new controller environment. They cover
FASTA validation/normalization, exact structure matching and sequence identity,
configuration paths, missing/partial results, subprocess failure and timeout,
checkpoint archive traversal and symlink rejection, ranking direction/ties,
missing values and weight validation. A fake external executable tests the
adapter contract; that test is not evidence of model inference.

`pip check` reports no broken requirements. The public synthetic ranking
example produces three ranked records. A private 40-record regression fixture
matches the original implementation on all 15 derived ranking fields. The
private fixture and experimental data are not distributed.

## Model inference scope

Real inference uses the public 76-residue 1UBQ FASTA/PDB fixture and existing,
separate model installations. Model weights and their environments are not
included in the controller installation. The initial CPU integration run
confirmed NetSolP (default ESM1b ensemble; score 0.81280947) and EvoEF2
(single-chain ComputeStability; total -337.41). Its controller was an existing
Python 3.10 environment during preparation of the new conda environment.
RP3Net exceeded that run's 180-second per-stage window.

The release does not claim fresh installation or inference validation of all
nine models. TemBERTure, TemStaPro, ESMC, ESM3, GATSol and Pro4S adapters have
not been exercised with real weights as part of this release. In particular,
GATSol/Pro4S need CUDA and Pro4S also needs a separate legacy MaSIF environment.
`envs/models.yml` is an unverified starting recipe, not a nine-model lockfile.
A successful `doctor` only establishes that configured paths exist.

Scores are computational model outputs, not experimental validation. The
single-record composite percentile is 0.5 by construction.

## Dedicated environment and built-wheel verification

The final CPU rerun in the dedicated Python 3.11.16 controller environment
completed with exit 0 for all three selected models:

| Model | Configuration | Result |
|---|---|---|
| NetSolP | Distilled, CPU | 0.8273101 |
| RP3Net | rp3net_v0.1_d checkpoint, CPU | 0.9142354726791382 |
| EvoEF2 | single matching chain, CPU | -337.41 |

The rerun used two CPU threads and a 600-second per-stage timeout. RP3Net
completed within this window; the earlier 180-second timeout was not counted
as a pass. See `examples/1ubq_results.csv` for the public result summary.

The wheel and source distribution were built with `python -m build`. The
wheel was installed into a separate target directory; import location was
verified, and both the ranking example and real EvoEF2 inference passed using
the installed wheel. No private configuration, weights or experimental records
are included in either distribution.

## Subsequent environment consolidation

The subsequent two-environment run passed all nine models on public 1UBQ.
See [the compatibility recipe and results](minimal_environment_zh.md);
the v0.1.0 validation above remains the historical release record.

## Subsequent two-environment validation (2026-09-08)

The main branch additionally passed all nine models on public 1UBQ and 10 private
designs split between two Linux GPU nodes. The latter yielded 90/90 successful
model statuses and 120 finite primary metrics after repairing APBS shared-library
resolution on one node and retrying only Pro4S. This is not an all-success initial
run or a same-design cross-node reproducibility test. Private inputs and scores
are not distributed. See [environment report](minimal_environment_zh.md) for
requirements, numerical comparisons and installation limitations. The original
v0.1.0 release validation above remains a historical record.

## Fresh-cluster installer validation (2026-09-08)

The new installer was exercised with an existing conda executable and a new,
isolated prefix: Python 3.10/controller installation, verified EvoEF2 source
copying, compilation, pinned upstream library import, launcher generation and
readiness checks succeeded. The public 1UBQ inference returned `evoef2_status=ok`
and energy **466.33**. GitHub downloads were cached from official pinned archives
when testing reruns; this is not an offline or cache-free network acceptance test.

A separate new MaSIF conda environment (Python 3.7, APBS 1.5, MSMS 2.6.1) was
created successfully. The installer-built multivalue reproduced **3.5** at the
center of a 2×2×2 grid with corner values 0–7. The installer-built Reduce processed
public 1UBQ and added **630 hydrogens**. These native tests do not establish a
complete Pro4S surface/inference pass. Legacy pip dependencies and the complete
modern dependency recipe still require fresh-prefix installation acceptance.

The final conda core recipe resolved successfully; pip resolution against the
existing compatible core also succeeded without changing it. Cache-free modern
resolution and the legacy pip installation were stopped during slow package
downloads; neither is counted as a completed fresh install.

The **23-test** automated suite now includes installer source/hash verification, archive
asset validation, path/symlink protection, preservation of modified sources,
resume behavior, GraphBolt patch safety, failure reporting, no-write planning
and launcher quoting. Shell syntax checks also pass. Miniforge bootstrap without
an existing conda and a complete fresh nine-model GPU run have **not** been
validated. The earlier 90/90 result remains evidence for the previous environment,
not for this new installer. NetSolP ONNX acquisition and any required upstream
account authorization remain user-supplied steps.
