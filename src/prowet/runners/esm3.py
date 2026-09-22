#!/usr/bin/env python3
"""Run the existing ESM3 perplexity script against a local HF snapshot."""

from __future__ import annotations

import argparse
import csv
import sys
import os
from pathlib import Path

import torch

ROOTS = [
    Path(
        os.environ.get(
            "HF_HUB_CACHE",
            str(
                Path(os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface")))
                / "hub"
            ),
        )
    ),
]


def local_snapshot() -> Path | None:
    candidates = []
    for root in ROOTS:
        for snapshot in root.glob("models--*--esm3-sm-open-v1/snapshots/*"):
            weight = snapshot / "data" / "weights" / "esm3_sm_open_v1.pth"
            if weight.is_file() and weight.stat().st_size > 0:
                candidates.append(snapshot)
    return candidates[-1] if candidates else None


def main() -> None:
    parser = argparse.ArgumentParser(description="ESM3 masked pseudo-perplexity")
    parser.add_argument("input")
    parser.add_argument("output_csv")
    parser.add_argument("--mask-batch-size", type=int, default=8)
    parser.add_argument(
        "--device",
        choices=["cuda", "cpu"],
        default=None,
        help="Torch device; defaults to CUDA when available.",
    )
    args = parser.parse_args()
    snapshot = local_snapshot()
    if snapshot is None:
        raise SystemExit("missing local ESM3 weights: esm3_sm_open_v1.pth")
    import esm.pretrained as pretrained
    import esm.utils.constants.esm3 as esm3_constants
    from esm.models.esm3 import ESM3
    from esm.sdk.api import ESMProtein

    def data_root(_model: str) -> Path:
        return snapshot

    # ESM3.from_pretrained imports load_local_model at call time, while the
    # builders retain data_root in pretrained.__globals__.
    esm3_constants.data_root = data_root
    pretrained.data_root = data_root

    def read_fasta(path: Path) -> list[tuple[str, str]]:
        records, name, chunks = [], None, []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if name is not None:
                    records.append((name, "".join(chunks).upper()))
                name, chunks = line[1:].split()[0], []
            else:
                chunks.append(line)
        if name is not None:
            records.append((name, "".join(chunks).upper()))
        return records

    requested_device = args.device
    if requested_device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("--device cuda requested but CUDA is unavailable")
    device = torch.device(
        requested_device or ("cuda" if torch.cuda.is_available() else "cpu")
    )
    model = ESM3.from_pretrained("esm3_sm_open_v1", device=device).eval()
    records = read_fasta(Path(args.input))
    results = []
    for name, sequence in records:
        try:
            reference = model.encode(ESMProtein(sequence=sequence)).sequence
            positions = list(range(1, len(sequence) + 1))
            log_probs = []
            # Activation memory grows with both sequence length and the
            # number of masked copies in a batch.  A fixed large batch works
            # for short proteins but can fail part-way through a mixed FASTA.
            # Keep the fast setting for short chains and cap long chains.
            if len(sequence) > 240:
                safe_batch_size = min(args.mask_batch_size, 24)
            elif len(sequence) > 160:
                safe_batch_size = min(args.mask_batch_size, 32)
            elif len(sequence) > 120:
                safe_batch_size = min(args.mask_batch_size, 64)
            else:
                safe_batch_size = args.mask_batch_size
            for start in range(0, len(positions), max(1, safe_batch_size)):
                batch_positions = positions[start : start + max(1, safe_batch_size)]
                masked = [
                    sequence[: pos - 1] + "<mask>" + sequence[pos:]
                    for pos in batch_positions
                ]
                tokens = torch.stack(
                    [model.encode(ESMProtein(sequence=s)).sequence for s in masked]
                )
                with torch.no_grad():
                    if device.type == "cuda":
                        with torch.autocast("cuda", dtype=torch.bfloat16):
                            logits = model(sequence_tokens=tokens).sequence_logits
                    else:
                        logits = model(sequence_tokens=tokens).sequence_logits
                logp = torch.log_softmax(logits.float(), dim=-1)
                for row, pos in enumerate(batch_positions):
                    log_probs.append(logp[row, pos, int(reference[pos])].cpu())
            ppl = torch.exp(-torch.stack(log_probs).mean()).item()
            results.append((name, sequence, f"{ppl:.6f}"))
            print(f"[ok] {name} len={len(sequence)} ppl={ppl:.6f}", file=sys.stderr)
        except Exception as exc:
            if device.type == "cuda":
                torch.cuda.empty_cache()
            print(f"[error] {name}: {exc}", file=sys.stderr)

    with Path(args.output_csv).open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "seq", "perplexity"])
        writer.writerows(results)


if __name__ == "__main__":
    main()
