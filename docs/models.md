# Model installation and configuration

The package contains integration code, not pretrained models. The repository
also includes six licensed upstream source subsets under `third_party/`. Install upstream
repositories at a fixed revision and obtain weights under their respective
licenses. Fill in `paths` in a JSON config; unconfigured paths fail explicitly.
`*_py` defaults to the current Python except when configured. It is usually
necessary to set it for each external environment. The bundled ESM and
TemBERTure runners are selected automatically, or overridden via `*_run`.

| Model | Upstream | Required path keys | Output |
|---|---|---|---|
| NetSolP | https://github.com/teevee112/NetSolP-1.0 | `netsolp_py`, `netsolp` (PredictionServer/predict.py), `netsolp_models` (PredictionServer/models) | predicted_solubility |
| RP3Net | https://github.com/RP3Net/RP3Net | `rp3net_py`, `rp3_repo`, `rp3_src` (repo/src), `rp3_ckpt` (weights/rp3net_v0.1_d.ckpt) | score |
| TemBERTure | https://github.com/ibmm-unibe-ch/TemBERTure | `temberture_py`, `temberture_models` (directory containing temBERTure_TM and temBERTure_CLS) | ensemble Tm, classification |
| TemStaPro | https://github.com/ievapudz/TemStaPro | `temstapro_py`, `temstapro` (entry script), `temstapro_dir` (repo), `prottrans` (local ProtTrans model) | t40/t55/t65 predictions |
| ESMC | https://github.com/evolutionaryscale/esm | `esmc_py` (ESM SDK environment) | masked pseudo-perplexity |
| ESM3 | https://github.com/evolutionaryscale/esm | `esm3_py` (ESM SDK environment) | masked pseudo-perplexity |
| GATSol | https://github.com/binbinbinv/GATSol | `gatsol_py`, `gatsol_repo`, `gatsol_ckpt` | Solubility_hat |
| Pro4S | https://github.com/TEKHOO/Pro4S | `pro4s_py`, `pro4s_root`, `masif_py` | Prediction |
| EvoEF2 | https://github.com/tommyhuangthu/EvoEF2 | `evoef2` (compiled executable) | ComputeStability Total |

## Recommended installation

Use [the fresh-cluster installer](install_zh.md) for new Linux x86_64 clusters.
It installs modern models in screen2, ESM SDK 3.1.1 in a separate module
directory using the same interpreter, and MaSIF in Python 3.7. The installer
uses `envs/fresh-core-requirements.txt` and `envs/fresh-masif-requirements.txt`.
The older `models.yml` and consolidation overlay are historical recipes.

Existing installations can use [the validated two-environment configuration](minimal_environment_zh.md).
All checkpoints remain external; per-model download sources, missing-asset
handling and native tool overrides are listed in the installation guide.

Model subprocesses may be expensive. Run a single public structure first,
inspect per-model status/raw values, then scale to a batch. Do not treat a
successful package install or `doctor` as proof of successful model inference.

## Configuration example: EvoEF2 + RP3Net

```json
{
  "paths": {
    "evoef2": "external/EvoEF2/EvoEF2",
    "rp3net_py": "~/miniconda3/envs/screen-models/bin/python",
    "rp3_repo": "external/RP3Net",
    "rp3_src": "external/RP3Net/src",
    "rp3_ckpt": "external/RP3Net/weights/rp3net_v0.1_d.ckpt"
  },
  "env": {
    "rp3net": {"HF_HOME": "~/.cache/huggingface"}
  }
}
```

## Third-party attribution

Cite the upstream model publications linked from their repositories. Six selected source subsets retain their original licenses and pinned revisions;
see [third-party attribution](../third_party/README.md). Model weights, compiled
binaries and databases are not distributed. Private workspace patches are applied at runtime by the
GATSol/Pro4S adapters. The bundled 1UBQ structure is public wwPDB data; see
https://www.wwpdb.org/about/usage-policies for the data usage policy.
