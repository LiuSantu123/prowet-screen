# ProWet

ProWet is the pre-experiment screening toolkit for soluble, stable protein
constructs. It runs configurable sequence and structure predictors, keeps raw
model outputs and statuses, and produces a ranked CSV for wet-lab prioritization.
The score is a within-batch decision aid, not a replacement for expression,
purification, or experimental validation.

## Install

```bash
git clone https://github.com/LiuSantu123/prowet-screen.git
cd prowet-screen
conda env create -f environment.yml
conda activate prowet
pip install -e .
prowet --version
```

For a fresh Linux x86_64 machine, `install.sh` can create the isolated runtime,
compile EvoEF2, and prepare model configuration:

```bash
bash install.sh --prefix "$HOME/software/prowet-runtime"
```

Model weights and gated upstream dependencies are intentionally not bundled.
See [model configuration](docs/models.md) and the [installation guide](docs/install_zh.md).

## Quick start

Rank an existing score table without installing model weights:

```bash
prowet rank examples/scores.csv -o output/ranked.csv
```

Run a configured screen:

```bash
prowet doctor --config config.json --models netsolp temberture evoef2
prowet run sequences.fasta --structures structures/ \
  --config config.json \
  --models netsolp rp3net temberture temstapro esmc esm3 gatsol pro4s evoef2 \
  --device cuda -o output/prowet.csv
```

FASTA IDs must be unique. Structure-aware models expect exactly one matching
`<design_id>.pdb`, `.cif`, or `.mmcif` file. A missing model is reported as a
status and is never silently replaced by a heuristic.

## What to review before experiments

The output includes raw scores, per-model statuses, normalized ranks, and
separate solubility and thermostability consensus columns. Review individual
metrics, sequence length, tags, aggregation risk, and the intended expression
system before selecting constructs. Different batches and different model
coverage are not directly comparable.

## Python API

```python
from prowet import screen

screen("sequences.fasta", "output/prowet.csv",
       models=["netsolp", "temberture"],
       config="config.json", device="cuda")
```

The API launches an isolated CLI process. See [中文使用说明](docs/usage_zh.md),
[model details](docs/models.md), and [validation](docs/validation.md) for the
full workflow. Run tests with:

```bash
python -m unittest discover -s tests -v
```

The integration code is MIT licensed. Model checkpoints, databases, and
third-party licenses remain governed by their upstream projects.
