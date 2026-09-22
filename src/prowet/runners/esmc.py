#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
import os
import inspect
from pathlib import Path
from typing import Any

VALID_AA = set("ACDEFGHIKLMNPQRSTVWYXBZUO")
SUPPORTED_ESMC_MODELS = {"esmc_300m", "esmc_600m"}
torch: Any = None
ESMC: Any = None
ESMProtein: Any = None
get_esmc_model_tokenizers: Any = None


def import_esmc_stack() -> None:
    global torch, ESMC, ESMProtein, get_esmc_model_tokenizers
    if torch is not None:
        return
    import torch as torch_module
    from esm.models.esmc import ESMC as esmc_class
    from esm.sdk.api import ESMProtein as esm_protein_class
    from esm.tokenization import get_esmc_model_tokenizers as tokenizer_factory

    torch = torch_module
    ESMC = esmc_class
    ESMProtein = esm_protein_class
    get_esmc_model_tokenizers = tokenizer_factory


def read_fasta_or_sequence(value: str) -> list[tuple[str, str]]:
    path = Path(value)
    if path.exists():
        records: list[tuple[str, str]] = []
        name: str | None = None
        chunks: list[str] = []
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if name is not None:
                    records.append((name, "".join(chunks)))
                name = line[1:].split()[0] or f"seq{len(records) + 1}"
                chunks = []
            else:
                chunks.append(line)
        if name is not None:
            records.append((name, "".join(chunks)))
        if not records:
            raise ValueError(f"No FASTA records found in {path}")
        return records

    seq = re.sub(r"\s+", "", value).upper()
    if not seq:
        raise ValueError("Empty input sequence")
    return [("sequence", seq)]


def clean_sequence(seq: str) -> str:
    seq = re.sub(r"\s+", "", seq).upper()
    seq = seq.replace("*", "")
    return "".join(aa if aa in VALID_AA else "X" for aa in seq)


def sequence_pseudo_perplexity(
    model: Any,
    seq: str,
    mask_batch_size: int,
) -> float:
    seq = clean_sequence(seq)
    if not seq:
        return float("nan")

    encoded = model.encode(ESMProtein(sequence=seq))
    if encoded.sequence is None:
        raise RuntimeError("ESMC tokenizer returned no sequence tokens")

    original = encoded.sequence.detach().clone()
    device = original.device
    mask_id = int(model.tokenizer.mask_token_id)
    log_probs: list[Any] = []

    # ESMC adds <cls> and <eos>, so residue i is token position i + 1.
    positions = list(range(1, len(seq) + 1))
    with torch.no_grad():
        for start in range(0, len(positions), mask_batch_size):
            batch_positions = positions[start : start + mask_batch_size]
            batch_tokens = original.unsqueeze(0).repeat(len(batch_positions), 1)
            for row, pos in enumerate(batch_positions):
                batch_tokens[row, pos] = mask_id
            output = model(sequence_tokens=batch_tokens.to(device))
            logits = output.sequence_logits
            batch_logp = torch.log_softmax(logits, dim=-1)
            for row, pos in enumerate(batch_positions):
                target = int(original[pos].item())
                log_probs.append(batch_logp[row, pos, target].float().cpu())

    mean_nll = -torch.stack(log_probs).mean().item()
    return math.exp(mean_nll)


def load_esmc_model(model_name: str, device: Any, use_flash_attn: bool) -> Any:
    if model_name not in SUPPORTED_ESMC_MODELS:
        allowed = ", ".join(sorted(SUPPORTED_ESMC_MODELS))
        raise RuntimeError(
            f"Unsupported ESMC model {model_name!r}. Supported models: {allowed}."
        )

    try:
        loader_options = {}
        if "use_flash_attn" in inspect.signature(ESMC.from_pretrained).parameters:
            loader_options["use_flash_attn"] = use_flash_attn
        model = ESMC.from_pretrained(
            model_name,
            device=device,
            **loader_options,
        )
    except Exception as exc:
        # The installed SDK may still call snapshot_download even when the
        # complete weight file is already in the local HF cache.  Fall back
        # to the local checkpoint for all loader/cache failures; re-raise
        # unrelated model-construction errors when no local weight exists.
        if not any(
            any(root.glob(glob))
            for root in [
                Path(
                    os.environ.get(
                        "HF_HUB_CACHE",
                        str(
                            Path(
                                os.environ.get(
                                    "HF_HOME", str(Path.home() / ".cache/huggingface")
                                )
                            )
                            / "hub"
                        ),
                    )
                ),
            ]
            for glob in [
                (
                    "models--biohub--esmc-300m-2024-12/snapshots/*/data/weights/"
                    "esmc_300m_2024_12_v0.pth"
                    if model_name == "esmc_300m"
                    else "models--biohub--esmc-600m-2024-12/snapshots/*/data/weights/"
                    "esmc_600m_2024_12_v0.pth"
                )
            ]
        ):
            raise
        specs = {
            "esmc_300m": {
                "d_model": 960,
                "n_heads": 15,
                "n_layers": 30,
                "repo_glob": "models--biohub--esmc-300m-2024-12/snapshots/*/data/weights/esmc_300m_2024_12_v0.pth",
            },
            "esmc_600m": {
                "d_model": 1152,
                "n_heads": 18,
                "n_layers": 36,
                "repo_glob": "models--biohub--esmc-600m-2024-12/snapshots/*/data/weights/esmc_600m_2024_12_v0.pth",
            },
        }
        spec = specs[model_name]
        constructor_options = {}
        if "use_flash_attn" in inspect.signature(ESMC).parameters:
            constructor_options["use_flash_attn"] = use_flash_attn
        model = ESMC(
            d_model=spec["d_model"],
            n_heads=spec["n_heads"],
            n_layers=spec["n_layers"],
            tokenizer=get_esmc_model_tokenizers(),
            **constructor_options,
        ).eval()
        cache_roots = [
            Path(
                os.environ.get(
                    "HF_HUB_CACHE",
                    str(
                        Path(
                            os.environ.get(
                                "HF_HOME", str(Path.home() / ".cache/huggingface")
                            )
                        )
                        / "hub"
                    ),
                )
            ),
        ]
        weight_candidates = sorted(
            candidate
            for root in cache_roots
            for candidate in root.glob(spec["repo_glob"])
        )
        if not weight_candidates:
            raise RuntimeError(
                f"Cannot find local {model_name} .pth weights after snapshot download"
            ) from exc
        state_dict = torch.load(weight_candidates[-1], map_location=device)
        model.load_state_dict(state_dict, strict=True)
        model = model.to(device)
        if device.type != "cpu":
            model = model.to(torch.bfloat16)
    return model


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute ESMC masked pseudo-perplexity for FASTA records."
    )
    parser.add_argument("input", help="FASTA file path or raw protein sequence")
    parser.add_argument("output_csv", help="Output CSV: name,seq,perplexity")
    parser.add_argument(
        "--model",
        default="esmc_600m",
        choices=sorted(SUPPORTED_ESMC_MODELS),
        help="ESMC model. esmc_600m is the default; esmc_300m is fastest.",
    )
    parser.add_argument(
        "--device",
        default=None,
        choices=["cuda", "cpu"],
        help="Torch device. Default: cuda when available, otherwise cpu.",
    )
    parser.add_argument(
        "--mask-batch-size",
        type=int,
        default=8,
        help="Number of masked positions per forward batch.",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=1200,
        help="Skip sequences longer than this length.",
    )
    parser.add_argument(
        "--no-flash-attn",
        action="store_true",
        help="Disable flash attention if the installed stack has issues.",
    )
    args = parser.parse_args()

    import_esmc_stack()
    if args.device is None:
        args.device = "cuda" if torch.cuda.is_available() else "cpu"

    records = read_fasta_or_sequence(args.input)
    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    device = torch.device(args.device)
    model = load_esmc_model(args.model, device, use_flash_attn=not args.no_flash_attn)
    model.eval()

    with output_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "seq", "perplexity"])
        for name, seq in records:
            clean = clean_sequence(seq)
            if len(clean) > args.max_length:
                print(
                    f"[skip] {name}: length {len(clean)} > {args.max_length}",
                    file=sys.stderr,
                )
                writer.writerow([name, clean, "nan"])
                continue
            try:
                ppl = sequence_pseudo_perplexity(
                    model,
                    clean,
                    max(1, args.mask_batch_size),
                )
                writer.writerow([name, clean, f"{ppl:.6f}"])
                print(f"[ok] {name} len={len(clean)} ppl={ppl:.6f}", file=sys.stderr)
            except RuntimeError:
                if args.device == "cuda":
                    torch.cuda.empty_cache()
                raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
