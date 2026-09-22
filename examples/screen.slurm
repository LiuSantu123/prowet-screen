#!/usr/bin/env bash
#SBATCH --job-name=prowet
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
set -euo pipefail
if [[ $# -ne 4 ]]; then
  echo 'Usage: sbatch --partition=YOUR_GPU_PARTITION --gres=gpu:1 examples/screen.slurm config.json input.fasta structures/ output.csv' >&2
  exit 2
fi
# Run from the repository root; conda must be available on the compute node.
conda run --no-capture-output -n prowet prowet run "$2" \
  --structures "$3" --config "$1" --models netsolp rp3net evoef2 \
  --device cuda --threads "${SLURM_CPUS_PER_TASK:-8}" -o "$4"
