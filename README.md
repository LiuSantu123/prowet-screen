# Protein Screen

A CLI and Python API for running nine protein screening adapters and collecting
sequence/structure metrics in a ranked CSV. Model paths and interpreters are
configured explicitly. Runs use isolated temporary workspaces. Linux is the
supported execution platform (POSIX process groups and upstream shell tools).

**[中文使用说明](docs/usage_zh.md)** · **[Model installation and configuration](docs/models.md)**

## Fresh cluster installer

```bash
git clone https://github.com/LiuSantu123/protein-screen.git && bash protein-screen/install.sh --prefix "$HOME/software/protein-screen-runtime"
```

See [空白集群安装与逐模型权重指引](docs/install_zh.md). This creates isolated
`screen2` + `masif` environments, builds EvoEF2, fetches external assets, and
writes a prefix-specific launcher/config plus a failure report. NetSolP ONNX
requires the official download package; gated models need upstream access.
Six permissively licensed source subsets are included in [third_party](third_party/README.md).
Package checks do not establish nine-model inference acceptance on a new cluster.

## Controller-only install

```bash
git clone https://github.com/LiuSantu123/protein-screen.git
cd protein-screen
conda env create -f environment.yml
conda activate protein-screen
protein-screen --version
```

The conda environment installs the **controller, structure parser and result
readers**. Model environments and weights are installed separately by the fresh installer
or configured manually; weights are not bundled. Existing installations can be reused. The default
recipe does not attempt to consolidate upstream model dependencies.
The recipe runs `pip install -e .`, so run it from the repository root.
Alternatively, install this package using `pip install .` in Python 3.10.12+.

A tested two-environment setup for all nine models is documented in
[最小环境与九模型验收](docs/minimal_environment_zh.md): **screen2 + masif**.
It now includes a portable `scripts/screen.sh` launcher, a
[`config.screen2.json`](examples/config.screen2.json) template, observed
package inventories and explicit APBS binary/shared-library requirements.
Validation covers public 1UBQ plus 10 private designs across two GPU nodes
(90/90 model statuses passed after a Pro4S dependency repair and targeted retry).
See the guide for the validated environment-clone workflow. The historical
bootstrap YAML is an overlay; use `install.sh` for the new fresh-install recipe.

## Try without model weights

```bash
protein-screen rank examples/scores.csv -o output/ranked.csv
```

The score CSV is synthetic. It verifies ranking and missing-value handling,
not biological prediction. Models are selected explicitly; missing models are
never substituted with heuristic scores.

## Run a real structure energy calculation

Install [EvoEF2](https://github.com/tommyhuangthu/EvoEF2) using its `build.sh`, then
save a configuration (keep the executable alongside its upstream `library/`):

```json
{"paths": {"evoef2": "/absolute/path/to/EvoEF2/EvoEF2"}}
```

```bash
protein-screen doctor --config config.json --models evoef2
protein-screen run examples/1ubq.fasta examples/1ubq.pdb \
  --config config.json --models evoef2 -o output/1ubq.csv
```

The 1UBQ fixture is public ubiquitin, obtained from
https://files.rcsb.org/download/1UBQ.pdb (PDB DOI: 10.2210/pdb1UBQ/pdb).
It is a workflow example, not a designed binder or experimental result.

## Multiple models

Edit `examples/config.json` to point to your installations. Relative paths are
resolved against the JSON file, not the working directory. `~` and environment
variables are expanded. The example paths are placeholders.

```bash
protein-screen run sequences.fasta --structures structures/ \
  --config config.json --models netsolp rp3net temberture temstapro \
  esmc esm3 gatsol pro4s evoef2 --device cuda -o output/screen.csv
```

Sequence-only runs may omit structures. GATSol and Pro4S adapters require CUDA
and structures; EvoEF2 runs on CPU. NetSolP and TemStaPro choose their device
upstream; CPU mode hides CUDA from all subprocesses. `--device cuda` permits
GPU use but does not guarantee every upstream stage uses it.

FASTA IDs must be unique and use letters, digits, dot, underscore or hyphen;
only canonical amino acids are accepted. NetSolP rejects a batch containing
sequences longer than 1022 residues, avoiding upstream silent truncation. A structure directory must contain
exactly one `<id>.pdb`, `<id>.cif` or `<id>.mmcif` per available design. Prefix
matching is intentionally unsupported. Missing structures produce explicit
statuses. A single structure file requires a single FASTA record.

Structural scoring extracts the unique chain segment matching the full FASTA
sequence. Terminal tags may be removed only after sequence identity is checked;
mismatches and ambiguous homomers are rejected. Other chains/ligands are not
scored: this tool reports single-protein developability metrics, not binding
energies or CID induction.

## Python API

```python
from protein_screen import screen

result = screen("sequences.fasta", "screen.csv",
                models=["netsolp", "rp3net"], config="config.json", device="cuda")
```

Each call launches an isolated CLI process. Nonzero exits raise
`subprocess.CalledProcessError`. CLI exit 0 means every selected model has a
finite result for every input, unless `--allow-partial` was explicitly passed.
Exit 2 reports invalid input or incomplete results; completed runs still write
a diagnostic CSV when models fail. `doctor` checks paths only, not dependencies,
weights integrity or inference. Inspect its JSON and use a real smoke run.

## Output and interpretation

- Raw scores and `<model>_status`; `not_selected` differs from missing/error.
- Batch percentile ranks with ties averaged; lower energy/perplexity is better.
- `screening_score`, `ranking_model_count`, `ranking_weight_coverage` and
  solubility/thermostability consensus columns. Missing values are `nan`, never 0.
- Default **legacy** weights retain the original ranking: NetSolP .25, RP3Net
  .10, Pro4S .20, GATSol .15, TemBERTure .15, TemStaPro .10, ESMC .05, ESM3 .05,
  EvoEF2 .10. Weights are renormalized over available positive-weight results.
  `--weights-json` overrides selected keys with finite nonnegative values.

These are **within-batch heuristic ranks**, not calibrated experimental success
probabilities. All available metrics for a single record yield percentile 0.5.
Different model coverage or different batches are not directly comparable.
Thermostability raw consensus mixes units and is retained only for compatibility;
use the individual metrics or normalized consensus. Total EvoEF2 energy is also
length dependent. Solubility, aggregation, expression and function are separate
phenotypes; high composite scores do not establish any of them experimentally.

`rank` can rerank an existing CSV with unique `id` values and any supported raw
metric columns. If model status columns are present, non-`ok` values are excluded.

## Resources, downloads and tests

`--threads` controls CPU thread limits; `--timeout` is a per-stage timeout
(default 2400 seconds). Lower `--mask-batch-size` if ESM runs exhaust memory.
Hugging Face is offline by default; `--allow-model-download` enables Hub access
for compatible runners. ESM3 still requires a predownloaded local snapshot.
Other upstream tools may use their own weight download mechanisms; install their
weights beforehand for an air-gapped run. Config `env` sets per-model cache or
library paths without changing the parent shell. Use trusted local repositories,
configurations and checkpoints; model adapters execute upstream code.

```bash
python -m unittest discover -s tests -v
```

See [validation](docs/validation.md) for the precise scope of release testing.
The MIT license covers this integration code. Third-party models, checkpoints
and tools retain their own licenses and access conditions; cite their papers.

To reproduce the tested Linux controller runtime exactly:

```bash
conda create -n protein-screen --file envs/conda-linux-64.lock
conda activate protein-screen
python -m pip install -r envs/controller-pip.txt
python -m pip install --no-deps .
```
