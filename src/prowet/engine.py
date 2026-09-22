#!/usr/bin/env python3
"""Unified sequence/structure screening for de-novo proteins.

Unavailable weights/features are kept as explicit status values; they are
never silently converted into zero scores.  Temporary model outputs are
removed automatically.
"""

from __future__ import annotations

import argparse, csv, json, math, os, re, signal, subprocess, tempfile, shutil, tarfile
from pathlib import Path
from typing import Any

from .config import load_config, MODEL_KEYS
import sys

D = {}
MODEL_ENV = {}
SELECTED = set()


def fasta(path: Path) -> list[tuple[str, str]]:
    records, name, chunks = [], None, []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name is not None:
                records.append((name, "".join(chunks).upper()))
            if not line[1:].strip():
                raise ValueError("empty FASTA identifier")
            name, chunks = line[1:].split()[0], []
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
                raise ValueError(
                    "FASTA IDs must use letters, digits, dot, underscore or hyphen"
                )
        elif name is None:
            raise ValueError("sequence before FASTA header")
        else:
            chunks.append(re.sub(r"\s+", "", line))
    if name is not None:
        records.append((name, "".join(chunks).upper()))
    if not records or any(not seq for _, seq in records):
        raise ValueError("FASTA contains no/empty records")
    if len({name for name, _ in records}) != len(records):
        raise ValueError("duplicate FASTA identifiers")
    if any(set(seq) - set("ACDEFGHIKLMNPQRSTVWY") for _, seq in records):
        raise ValueError("only the 20 canonical amino acids are supported")
    return records


def base(value: Any) -> str:
    return str(value or "").split("|", 1)[0].split()[0]


def num(value: Any) -> float:
    try:
        x = float(value)
        return x if math.isfinite(x) else math.nan
    except (TypeError, ValueError):
        return math.nan


def table(path: Path, delim=",") -> dict[str, dict[str, str]]:
    if path.suffix.lower() == ".xlsx":
        import openpyxl

        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            values = list(workbook.active.values)
        finally:
            workbook.close()
        if not values:
            return {}
        headers = [str(x or "") for x in values[0]]
        rows = [dict(zip(headers, row)) for row in values[1:]]
    else:
        with path.open(newline="") as h:
            rows = list(csv.DictReader(h, delimiter=delim))
    out = {}
    for r in rows:
        for k in ("id", "sid", "name", "protein_id", "uniprot_id"):
            if r.get(k):
                out.setdefault(str(r[k]).split()[0], r)
                out.setdefault(base(r[k]), r)
    return out


def run(
    cmd: list[Any],
    cwd: Path | None,
    output: Path | None,
    timeout: int,
    env_extra: dict[str, str | None] | None = None,
    delim=",",
) -> dict[str, Any]:
    for item in cmd[:2]:
        if isinstance(item, Path) and not item.exists():
            return {"status": "missing_executable:" + str(item), "rows": {}, "log": ""}
    env = os.environ.copy()
    for key, value in (env_extra or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    try:
        proc = subprocess.Popen(
            [str(x) for x in cmd],
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        return {"status": f"launch_error:{exc}", "rows": {}, "log": ""}
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, _ = proc.communicate()
        log = (stdout or "").replace("\n", " ")[-1200:]
        return {
            "status": f"timeout_{timeout}s" + (":" + log if log else ""),
            "rows": {},
            "log": log,
        }
    log = (stdout or "").replace("\n", " ")[-1200:]
    if proc.returncode:
        return {"status": f"error_exit_{proc.returncode}:{log}", "rows": {}, "log": log}
    if output is None:
        return {
            "status": (
                "ok_no_output"
                if proc.returncode == 0
                else f"error_exit_{proc.returncode}:{log}"
            ),
            "rows": {},
            "log": log,
        }
    if not output.exists() or output.stat().st_size == 0:
        # Some upstream scripts catch their own exception and exit 0.  Keep
        # the tail of their captured log in the status so a missing artifact
        # remains diagnosable in the final CSV/console report.
        return {"status": f"error_empty_output:{log}", "rows": {}, "log": log}
    try:
        return {"status": "ok", "rows": table(output, delim), "log": log}
    except Exception as e:
        return {"status": f"error_parse:{e}", "rows": {}, "log": log}


def sequence_models(args: argparse.Namespace, work: Path) -> dict[str, dict[str, Any]]:
    outputs = {
        m: {"status": "not_selected", "rows": {}} for m in MODEL_KEYS if m != "evoef2"
    }
    jobs = {
        "netsolp": (
            [
                D["netsolp_py"],
                D["netsolp"],
                "--FASTA_PATH",
                args.fasta,
                "--OUTPUT_PATH",
                work / "netsolp.csv",
                "--MODELS_PATH",
                D["netsolp_models"],
                "--MODEL_TYPE",
                args.netsolp_model_type,
                "--PREDICTION_TYPE",
                "S",
                "--NUM_THREADS",
                args.threads,
            ],
            D["netsolp"].parent,
            work / "netsolp.csv",
            {},
        ),
        "temberture": (
            [
                D["temberture_py"],
                D["temberture_run"],
                args.fasta,
                "-o",
                work / "temberture.csv",
                "--device",
                args.device,
                "--tm_models",
                *[
                    D["temberture_models"] / "temBERTure_TM" / f"replica{i}"
                    for i in (1, 2, 3)
                ],
                "--cls_model",
                D["temberture_models"] / "temBERTure_CLS",
            ],
            work,
            work / "temberture.csv",
            {},
        ),
        "temstapro": (
            [
                D["temstapro_py"],
                D["temstapro"],
                "-f",
                args.fasta,
                "-d",
                D["prottrans"],
                "-t",
                D["temstapro_dir"],
                "-e",
                work / "embeddings",
                "--mean-output",
                work / "temstapro.tsv",
            ],
            D["temstapro_dir"],
            work / "temstapro.tsv",
            {"PYTORCH_CUDA_ALLOC_CONF": None},
        ),
        "rp3net": (
            [
                D["rp3net_py"],
                "-m",
                "RP3Net.rp3_main",
                "-p",
                D["rp3_ckpt"],
                "-f",
                args.fasta,
                "-o",
                work / "rp3.csv",
                "-d",
                args.device,
                "-b",
                args.batch_size,
                "--no-progress",
            ],
            D["rp3_repo"],
            work / "rp3.csv",
            {"PYTHONPATH": str(D["rp3_src"])},
        ),
        "esmc": (
            [
                D["esmc_py"],
                D["esmc_run"],
                args.fasta,
                work / "esmc.csv",
                "--model",
                args.esmc_model,
                "--device",
                args.device,
                "--mask-batch-size",
                args.mask_batch_size,
                "--no-flash-attn",
            ],
            work,
            work / "esmc.csv",
            {},
        ),
        "esm3": (
            [
                D["esm3_py"],
                D["esm3_run"],
                args.fasta,
                work / "esm3.csv",
                "--device",
                args.device,
                "--mask-batch-size",
                args.mask_batch_size,
            ],
            work,
            work / "esm3.csv",
            {},
        ),
    }
    for model in jobs:
        if model not in SELECTED:
            continue
        if model == "netsolp" and any(len(seq) > 1022 for _, seq in fasta(args.fasta)):
            outputs[model] = {
                "status": "unsupported_sequence_length_over_1022",
                "rows": {},
            }
            continue
        missing = [key for key in MODEL_KEYS[model] if not D[key].exists()]
        if missing:
            outputs[model] = {
                "status": "missing_config_or_path:" + ",".join(missing),
                "rows": {},
            }
            continue
        cmd, cwd, target, env = jobs[model]
        env.update(MODEL_ENV.get(model, {}))
        env.update(
            {"OMP_NUM_THREADS": str(args.threads), "MKL_NUM_THREADS": str(args.threads)}
        )
        if not args.allow_model_download:
            env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        outputs[model] = run(
            cmd,
            cwd,
            target,
            args.timeout,
            env,
            delim="\t" if model == "temstapro" else ",",
        )
    return outputs


def structure_for(ident: str, source: Path | None) -> Path | None:
    if source is None:
        return None
    if source.is_file():
        return source
    candidates = [source / (ident + suffix) for suffix in (".pdb", ".cif", ".mmcif")]
    candidates = [p for p in candidates if p.is_file()]
    if len(candidates) > 1:
        raise ValueError(f"ambiguous structures for {ident}: {candidates}")
    return candidates[0] if candidates else None


def write_sequence_matched_pdb(src: Path, sequence: str, dest: Path) -> None:
    """Require a unique exact sequence match; allow terminal tags, never blind trimming."""
    import gemmi

    structure = gemmi.read_structure(str(src))
    matches = []
    for chain in structure[0]:
        residues = [
            r
            for r in chain
            if any(a.name == "CA" for a in r)
            and gemmi.find_tabulated_residue(r.name).is_amino_acid()
        ]
        letters = "".join(
            gemmi.find_tabulated_residue(r.name).one_letter_code.upper()
            for r in residues
        )
        start = letters.find(sequence)
        while start >= 0:
            matches.append(residues[start : start + len(sequence)])
            start = letters.find(sequence, start + 1)
    if len(matches) != 1:
        raise ValueError(
            f"expected one exact sequence match in {src.name}, found {len(matches)}"
        )
    out = gemmi.Structure()
    out.cell, out.spacegroup_hm = structure.cell, structure.spacegroup_hm
    model, chain = gemmi.Model("1"), gemmi.Chain("A")
    for residue in matches[0]:
        chain.add_residue(residue)
    model.add_chain(chain)
    out.add_model(model)
    out.write_pdb(str(dest))


def extract_checkpoint_archive(checkpoint: Path, destination: Path) -> None:
    """Accept only files/directories contained within a private destination."""
    root = destination.resolve()
    with tarfile.open(checkpoint, "r:gz") as archive:
        for member in archive.getmembers():
            target = (root / member.name).resolve()
            if not target.is_relative_to(root) or not (
                member.isfile() or member.isdir()
            ):
                raise ValueError("unsafe checkpoint archive member")
            if target == root and not member.isdir():
                raise ValueError("invalid checkpoint archive root")
        archive.extractall(root, filter="data")


def gatsol(
    records, source: Path, work: Path, timeout: int, checkpoint: Path | None = None
) -> dict[str, Any]:
    """Run the upstream GATSol prediction workflow in an isolated directory.

    GATSol's scripts use relative paths and mutate NEED_to_PREPARE, so an
    isolated symlink/copy workspace is safer than pointing them at the user's
    checkout.  The official checkpoint is intentionally required; no fallback
    heuristic is substituted for a neural prediction.
    """
    ckpt_candidates = [
        checkpoint or D["gatsol_ckpt"],
        D["gatsol_repo"] / "check_point/best_model/best_model.pkl",
        D["gatsol_repo"] / "check_point/best_model/best_model.tar.gz",
    ]
    ckpt = next((p for p in ckpt_candidates if p.is_file()), None)
    if ckpt is None:
        return {"status": "missing_checkpoint_download_from_GATSol_readme", "rows": {}}
    if not D["gatsol_repo"].is_dir():
        return {"status": "missing_GATSol_repository", "rows": {}}

    root = work / "gatsol"
    prep = root / "Predict/NEED_to_PREPARE"
    try:
        # The released checkout keeps the complete prediction entrypoints
        # under ``Predict/tools`` (there is no ``Predict/Predict.py`` at the
        # repository level).  Copy that directory as-is into the private
        # working tree; Predict.sh then resolves all helpers relative to it.
        for rel in ("tools",):
            src = D["gatsol_repo"] / "Predict" / rel
            dst = root / "Predict" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, symlinks=False)
            else:
                shutil.copy2(src, dst)
        feature_script = root / "Predict/tools/feature_extract/feature_extra.py"
        feature_text = feature_script.read_text()
        # The released feature extractor still contains the authors' private
        # /home/bli/homology paths.  All prediction inputs are in this
        # adapter's private NEED_to_PREPARE directory.
        feature_text = feature_text.replace(
            "/home/bli/homology/feature_extract/list371.csv",
            "./NEED_to_PREPARE/list.csv",
        )
        feature_text = feature_text.replace(
            "/home/bli/homology/colabfold_cm_371", "./NEED_to_PREPARE/cm"
        )
        feature_text = feature_text.replace(
            "/home/bli/homology/colabfold_fasta_371", "./NEED_to_PREPARE/fasta"
        )
        feature_text = feature_text.replace(
            "/home/bli/homology/colabfold_pkl_371", "./NEED_to_PREPARE/pkl"
        )
        feature_text = feature_text.replace(
            "/home/bli/homology/feature_extract/Protein_parameters_setting.json",
            "./tools/feature_extract/Protein_parameters_setting.json",
        )
        feature_text = feature_text.replace(
            "/home/bli/homology/feature_extract/log.log",
            "./tools/feature_extract/log.log",
        )
        feature_script.write_text(feature_text)
        # The upstream helper hard-codes ``conda activate pyg``.  That old
        # environment is intentionally not part of the current inventory;
        # the copied helper must inherit the screening interpreter instead.
        cm_script = root / "Predict/tools/pdb_to_cm/pdb_to_cm.sh"
        if cm_script.exists():
            cm_text = cm_script.read_text()
            cm_text = re.sub(
                r"\n\s*eval \"\$\(conda shell\.bash hook\)\"\n\s*conda activate pyg\n",
                "\n",
                cm_text,
            )
            cm_script.write_text(cm_text)
        # Older PyG releases serialized GATConv's homogeneous projection as
        # ``lin_src``/``lin_dst``.  Current screening PyG uses one ``lin``
        # parameter for the same homogeneous graph.  The supplied checkpoint
        # has identical src/dst tensors, so normalize only the state-dict
        # keys in the private copy; model weights themselves are unchanged.
        predict_script = root / "Predict/tools/Predict.py"
        predict_text = predict_script.read_text()
        old_load = 'model.load_state_dict(torch.load("../check_point/best_model/best_model.pt"))'
        new_load = """checkpoint = torch.load("../check_point/best_model/best_model.pt", map_location="cpu")
for layer in range(2):
    src_key = f"convs.{layer}.lin_src.weight"
    dst_key = f"convs.{layer}.lin_dst.weight"
    lin_key = f"convs.{layer}.lin.weight"
    if lin_key not in checkpoint and src_key in checkpoint:
        if dst_key in checkpoint and not torch.equal(checkpoint[src_key], checkpoint[dst_key]):
            raise RuntimeError("GATSol source/destination projections differ")
        checkpoint[lin_key] = checkpoint.pop(src_key)
        checkpoint.pop(dst_key, None)
model.load_state_dict(checkpoint)"""
        if old_load not in predict_text:
            raise RuntimeError(
                "unsupported GATSol Predict.py checkpoint-loading layout"
            )
        predict_script.write_text(predict_text.replace(old_load, new_load))
        # Predict.py resolves the checkpoint from ../check_point.
        (root / "check_point").mkdir()
        (root / "check_point/best_model").mkdir()
        if ckpt.suffixes[-2:] == [".tar", ".gz"] or ckpt.suffix == ".tgz":
            # Accept the exact archive name supplied by the authors.  Extract
            # only regular files below a private temporary directory and
            # reject path traversal before the archive is used.
            unpack = work / "gatsol_checkpoint_unpack"
            unpack.mkdir()
            extract_checkpoint_archive(ckpt, unpack)
            # The author-provided archive names the selected checkpoint with
            # its validation metrics (for example
            # ``best_model_0.519_0.426.pt``), while Predict.py expects the
            # normalized path ``best_model.pt``.
            extracted = [
                p
                for p in unpack.rglob("*")
                if p.is_file()
                and (
                    p.name in {"best_model.pkl", "best_model.pt"}
                    or (p.suffix == ".pt" and p.name.startswith("best_model_"))
                )
            ]
            if not extracted:
                return {"status": "checkpoint_archive_has_no_best_model", "rows": {}}
            ckpt = extracted[0]
        os.symlink(ckpt, root / "check_point/best_model/best_model.pt")
        for sub in ("fasta", "pdb"):
            (prep / sub).mkdir(parents=True)

        rows = []
        for ident, seq in records:
            src = structure_for(ident, source)
            if not src:
                continue
            pdb = prep / "pdb" / f"{base(ident)}.pdb"
            write_sequence_matched_pdb(src, seq, pdb)
            (prep / "fasta" / f"{base(ident)}.fasta").write_text(
                f">{base(ident)}\n{seq}\n"
            )
            rows.append((base(ident), seq))
        if not rows:
            return {"status": "missing_structure", "rows": {}}
        with (prep / "list.csv").open("w", newline="") as h:
            w = csv.writer(h)
            w.writerow(["id", "sequence"])
            w.writerows(rows)
        # Predict.sh and its helper scripts invoke a bare ``python``.  Pin
        # that lookup to screening so the caller's activated environment
        # cannot silently change the model implementation.
        gatsol_env = {
            "PATH": str(D["gatsol_py"].parent) + os.pathsep + os.environ.get("PATH", "")
        }
        result = run(
            ["bash", "tools/Predict.sh"],
            root / "Predict",
            root / "Predict/Output.csv",
            timeout,
            {**MODEL_ENV.get("gatsol", {}), **gatsol_env},
        )
        if result["status"] != "ok":
            return result
        # The generic CSV parser indexes id and base(id); normalize the score
        # key while retaining the upstream row for future fields.
        for key, row in list(result["rows"].items()):
            if "Solubility_hat" in row:
                row["score"] = row["Solubility_hat"]
        return result
    except Exception as exc:
        return {"status": f"adapter_error:{exc}", "rows": {}}


def pro4s(
    records,
    source: Path,
    work: Path,
    timeout: int,
    masif_python: Path | None = None,
    msms_bin: Path | None = None,
    pdb2pqr_bin: Path | None = None,
    apbs_bin: Path | None = None,
    multivalue_bin: Path | None = None,
) -> dict[str, Any]:
    """Run the upstream Pro4S workflow without modifying its checkout.

    Pro4S is not a sequence-only predictor: it requires MaSIF surface files,
    structural HDF5 features and ESM2-3B embeddings.  The learned-model stage
    runs in the shared screening interpreter; this adapter refuses to produce
    a score until the separate MaSIF environment and its executables are
    present.
    """
    root_src = D["pro4s_root"]
    if not root_src.is_dir():
        return {"status": "missing_Pro4S_repository", "rows": {}}
    if not D["pro4s_py"].is_file():
        return {"status": "missing_screening_python", "rows": {}}
    masif_exe = masif_python or D["masif_py"]
    if not masif_exe.is_file():
        return {"status": "missing_masif_env_create_masif_environment", "rows": {}}

    # MaSIF's scripts invoke these names through PATH.  Check the environment
    # first, then PATH, so a partially-created environment is not mistaken for
    # a valid prediction setup.
    masif_bin = masif_exe.parent

    # MaSIF installations commonly keep the legacy binaries outside the
    # Python environment (notably APBS/PDB2PQR).  Permit explicit paths while
    # retaining the conventional same-bin defaults.
    def tool_path(explicit: Path | None, name: str) -> Path:
        if explicit is not None:
            return explicit
        # Keep legacy MaSIF binaries preferred, but allow compatible tools
        # installed in screening (currently pdb2pqr) without copying them
        # into or modifying the MaSIF prefix.
        candidates = [masif_bin / name, D["pro4s_py"].parent / name]
        if name == "msms":
            candidates.append(root_src / "tools/msms/bin/msms")
        elif name == "multivalue":
            candidates.append(root_src / "tools/apbs15/bin/multivalue")
        elif name == "apbs":
            candidates.append(Path(shutil.which("apbs") or masif_bin / "apbs"))
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return masif_bin / name

    msms = tool_path(msms_bin, "msms")
    pdb2pqr = tool_path(pdb2pqr_bin, "pdb2pqr")
    apbs = tool_path(apbs_bin, "apbs")
    multivalue = tool_path(multivalue_bin, "multivalue")
    missing = [
        name
        for name, path in (
            ("msms", msms),
            ("pdb2pqr", pdb2pqr),
            ("apbs", apbs),
            ("multivalue", multivalue),
        )
        if not Path(path).is_file()
    ]
    if missing:
        return {
            "status": "missing_masif_dependency_" + "_or_".join(missing),
            "rows": {},
        }
    # MaSIF reads these variables at import time.  Set them in the private
    # subprocess only; the user's shell and all other environments remain
    # untouched.
    masif_env = {
        **MODEL_ENV.get("pro4s", {}),
        "MSMS_BIN": str(msms),
        "PDB2PQR_BIN": str(pdb2pqr),
        "APBS_BIN": str(apbs),
        "MULTIVALUE_BIN": str(multivalue),
    }
    # The legacy MaSIF ``multivalue`` executable is dynamically linked and
    # does not carry an rpath.  APBS bundles may place its libraries beside
    # the binary, one directory above it, or in lib64; expose all of these
    # locations only to the private Pro4S subprocess.
    multivalue_root = Path(multivalue).parent.parent
    legacy_lib_dirs = [
        Path(multivalue).parent,
        multivalue_root / "lib",
        multivalue_root / "lib64",
        Path(apbs).parent,
    ]
    legacy_lib_dirs = [str(p) for p in legacy_lib_dirs if p.is_dir()]
    if legacy_lib_dirs:
        masif_env["LD_LIBRARY_PATH"] = os.pathsep.join(
            legacy_lib_dirs
            + (
                [os.environ["LD_LIBRARY_PATH"]]
                if os.environ.get("LD_LIBRARY_PATH")
                else []
            )
        )
    checkpoint = root_src / "checkpoints/finetune.ckpt"
    if not checkpoint.is_file():
        return {"status": "missing_Pro4S_finetune_checkpoint", "rows": {}}

    root = work / "pro4s"
    scripts_src = root_src / "scripts"
    try:
        # The upstream scripts use fixed ../test and ../checkpoints paths and
        # rename/overwrite files.  A private copy keeps all such side effects
        # inside TemporaryDirectory.
        shutil.copytree(scripts_src, root / "scripts", symlinks=False)
        shutil.copytree(root_src / "checkpoints", root / "checkpoints", symlinks=True)
        # ``copytree`` preserves the repository's 0644 mode, but the legacy
        # MaSIF driver calls one helper as ``./script.sh``.  Make executable
        # bits and scratch directories available only in this private copy.
        for script in (root / "scripts/masif").rglob("*.sh"):
            script.chmod(script.stat().st_mode | 0o111)
        masif_data = root / "scripts/masif/data/masif_site/data_preparation"
        (masif_data / "00-raw_pdbs").mkdir(parents=True, exist_ok=True)
        # prepare_masif.py's downstream helper removes this legacy directory
        # unconditionally, so it must exist even for a fresh private copy.
        (masif_data / "01-benchmark_pdbs").mkdir(parents=True, exist_ok=True)
        (masif_data / "01-benchmark_surfaces").mkdir(parents=True, exist_ok=True)
        # The released MaSIF wrapper passes ``--ff=parse``.  PDB2PQR 3.x
        # accepts the same force field only as ``PARSE``.  Use a private
        # compatibility launcher rather than patching the installed tool or
        # any user's environment.
        pdb2pqr_compat = root / "pdb2pqr_compat.py"
        pdb2pqr_compat.write_text(
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            f"real = {str(pdb2pqr)!r}\n"
            "raw = ['--ff=PARSE' if x == '--ff=parse' else x for x in sys.argv[1:]]\n"
            "# MaSIF uses the old form: --apbs-input INPUT_PDB OUTPUT_BASE.\n"
            "# PDB2PQR 3.x requires an APBS output path plus INPUT_PDB OUTPUT.\n"
            "if '--apbs-input' in raw:\n"
            "    i = raw.index('--apbs-input')\n"
            "    if i + 2 < len(raw) and not raw[i + 1].startswith('-'):\n"
            "        input_pdb, output_base = raw[i + 1:i + 3]\n"
            "        raw[i:i + 3] = ['--apbs-input', output_base + '.in', input_pdb, output_base]\n"
            "args = raw\n"
            "import pathlib, subprocess\n"
            "rc = subprocess.call([real] + args)\n"
            "# PDB2PQR 3.x no longer emits the legacy marker that MaSIF\n"
            "# removes unconditionally after APBS; create it only as a\n"
            "# private cleanup compatibility marker.\n"
            "if '--apbs-input' in args:\n"
            "    i = args.index('--apbs-input')\n"
            "    if i + 3 < len(args):\n"
            "        pathlib.Path(args[i + 3] + '-input.p').touch()\n"
            "sys.exit(rc)\n"
        )
        pdb2pqr_compat.chmod(pdb2pqr_compat.stat().st_mode | 0o111)
        masif_env["PDB2PQR_BIN"] = str(pdb2pqr_compat)
        test = root / "test"
        pdb_dir = test / "pdb"
        result_dir = test / "result"
        pdb_dir.mkdir(parents=True)
        result_dir.mkdir(parents=True)
        test_txt = test / "test.txt"
        names = []
        for index, (ident, seq) in enumerate(records):
            src = structure_for(ident, source)
            if not src:
                continue
            safe = f"seq{index:05d}"
            pdb = pdb_dir / f"{safe}.pdb"
            write_sequence_matched_pdb(src, seq, pdb)
            names.append((safe, ident))
        if not names:
            return {"status": "missing_structure", "rows": {}}
        test_txt.write_text("".join(f"{safe}_0\n" for safe, _ in names))

        # The legacy MaSIF scripts need Python 3.7/TensorFlow 1.x, whereas
        # Pro4S' feature and GNN scripts need the modern screening stack
        # (pandas, plyfile, torch-geometric).  A single PATH ordering cannot
        # satisfy both, so select the interpreter per stage in the private
        # subprocess environment.  Nothing in either Conda environment is
        # modified by this dispatch.
        masif_env_run = os.environ.copy()
        masif_env_run.update(masif_env)
        masif_env_run["PATH"] = (
            str(masif_bin) + os.pathsep + masif_env_run.get("PATH", "")
        )
        masif = run(
            ["bash", "masif.sh"], root / "scripts", None, timeout, masif_env_run
        )
        if masif["status"] != "ok_no_output":
            return {"status": "masif_" + masif["status"], "rows": {}}
        generated_surfaces = list((test / "surface").glob("*.ply"))
        if len(generated_surfaces) < len(names):
            masif_log = masif.get("log", "")
            return {
                "status": "masif_no_surface_"
                + str(len(generated_surfaces))
                + "_of_"
                + str(len(names))
                + (":" + masif_log if masif_log else ""),
                "rows": {},
            }
        screening_env_run = os.environ.copy()
        screening_env_run.update(masif_env)
        screening_env_run["PATH"] = (
            str(D["pro4s_py"].parent)
            + os.pathsep
            + str(masif_bin)
            + os.pathsep
            + screening_env_run.get("PATH", "")
        )
        features = run(
            ["bash", "seq_structure_feature.sh"],
            root / "scripts",
            None,
            timeout,
            screening_env_run,
        )
        if features["status"] != "ok_no_output":
            return {"status": "feature_generation_" + features["status"], "rows": {}}
        prediction = run(
            [D["pro4s_py"], "test.py", "-ck_point", "finetune", "-gpu_num", "1"],
            root / "scripts",
            test / "result/test.xlsx",
            timeout,
            screening_env_run,
        )
        if prediction["status"] != "ok":
            # Pro4S' upstream test.py catches exceptions and may still exit
            # successfully.  Include private preprocessing diagnostics in
            # the status instead of returning an opaque empty result.
            diagnostics = []
            for name in ("error.txt", "error_surface.txt"):
                path = test / name
                if path.is_file() and path.stat().st_size:
                    diagnostics.append(
                        name + "=" + path.read_text()[-800:].replace("\n", " ")
                    )
            try:
                import h5py

                for name in (
                    "whole_edge_feature.hdf5",
                    "all_structure_feature_test.hdf5",
                ):
                    path = test / name
                    if path.is_file():
                        with h5py.File(path, "r") as handle:
                            diagnostics.append(
                                name + "_keys=" + ",".join(list(handle.keys())[:20])
                            )
            except Exception as exc:
                diagnostics.append("hdf5_diagnostic_error=" + str(exc))
            if diagnostics:
                prediction["status"] += ";" + ";".join(diagnostics)
            return prediction
        # Translate temporary seqNNNN identifiers back to the FASTA IDs.
        reverse = {safe: ident for safe, ident in names}
        rows = {}
        for key, row in prediction["rows"].items():
            raw = str(row.get("name", key)).split(".", 1)[0]
            ident = reverse.get(raw, raw)
            row["score"] = row.get("Prediction")
            rows[ident] = row
            rows[base(ident)] = row
        return {"status": "ok", "rows": rows}
    except Exception as exc:
        return {"status": f"adapter_error:{exc}", "rows": {}}


def evoef2(
    records, source: Path | None, work: Path, timeout: int
) -> dict[str, dict[str, Any]]:
    out = {}
    for ident, sequence in records:
        item = {"status": "not_selected", "energy": math.nan}
        out[ident] = item
        if "evoef2" not in SELECTED:
            continue
        src = structure_for(ident, source)
        if src is None:
            item["status"] = "missing_structure"
            continue
        if not D["evoef2"].is_file():
            item["status"] = "missing_executable"
            continue
        pdb = work / (ident + "_energy.pdb")
        try:
            write_sequence_matched_pdb(src, sequence, pdb)
            result = run(
                [D["evoef2"], "--command=ComputeStability", f"--pdb={pdb}"],
                D["evoef2"].parent,
                None,
                timeout,
                MODEL_ENV.get("evoef2"),
            )
            item["status"] = result["status"]
            if result["status"] != "ok_no_output":
                continue
            match = re.search(r"Total\s*=\s*([-+0-9.eE]+)", result["log"], re.I)
            item["energy"] = num(match.group(1)) if match else math.nan
            item["status"] = (
                "ok" if math.isfinite(item["energy"]) else "error_no_energy_parsed"
            )
        except Exception as exc:
            item["status"] = f"adapter_error:{exc}"
    return out


def percentile(values: list[float], value: float, high=True) -> float:
    vals = sorted(x for x in values if math.isfinite(x))
    if not vals or not math.isfinite(value):
        return math.nan
    if len(vals) == 1 or vals[0] == vals[-1]:
        return 0.5
    rank = sum(x < value for x in vals) + 0.5 * sum(x == value for x in vals)
    score = rank / len(vals)
    return score if high else 1 - score


def score_rows(rows: list[dict[str, Any]], weights_file: str | None) -> None:
    weights = {
        "netsolp_score": 0.25,
        "rp3net_score": 0.10,
        "pro4s_score": 0.20,
        "gatsol_score": 0.15,
        "temberture_tm": 0.15,
        "temstapro_t55_raw": 0.10,
        "esmc_perplexity": 0.05,
        "esm3_perplexity": 0.05,
        "evoef2_energy": 0.10,
    }
    if weights_file:
        custom = json.loads(Path(weights_file).read_text())
        if not isinstance(custom, dict) or set(custom) - set(weights):
            raise ValueError("weights must be an object containing known metric keys")
        if any(
            isinstance(v, bool)
            or not isinstance(v, (float, int))
            or not math.isfinite(v)
            or v < 0
            for v in custom.values()
        ):
            raise ValueError("weights must be finite nonnegative numbers")
        weights.update(custom)
    directions = {
        "evoef2_energy": False,
        "esmc_perplexity": False,
        "esm3_perplexity": False,
    }
    all_keys = set(weights) | set(directions)
    pools = {k: [num(r.get(k)) for r in rows] for k in all_keys}
    for r in rows:
        parts = []
        for k, w in weights.items():
            s = percentile(pools[k], num(r.get(k)), k not in directions)
            r[k + "_norm"] = s
            if math.isfinite(s) and w > 0:
                parts.append((s, w))
        for k, high in directions.items():
            r[k + "_norm"] = percentile(pools[k], num(r.get(k)), high)
        r["screening_score"] = (
            sum(s * w for s, w in parts) / sum(w for _, w in parts)
            if parts
            else math.nan
        )
        total_weight = sum(w for w in weights.values() if w > 0)
        r["ranking_model_count"] = len(parts)
        r["ranking_weight_coverage"] = (
            sum(w for _, w in parts) / total_weight if total_weight else math.nan
        )
        for name, keys in {
            "solubility_consensus": [
                "netsolp_score",
                "rp3net_score",
                "pro4s_score",
                "gatsol_score",
            ],
            "thermostability_consensus": ["temberture_tm", "temstapro_t55_raw"],
        }.items():
            raw = [num(r.get(k)) for k in keys if math.isfinite(num(r.get(k)))]
            normalized = [
                num(r.get(k + "_norm"))
                for k in keys
                if math.isfinite(num(r.get(k + "_norm")))
            ]
            r[name] = sum(raw) / len(raw) if raw else math.nan
            # Raw values can use different units (°C versus probability).
            r[name + "_norm"] = (
                sum(normalized) / len(normalized) if normalized else math.nan
            )
        r["solubility_model_count"] = sum(
            math.isfinite(num(r.get(k)))
            for k in ("netsolp_score", "rp3net_score", "pro4s_score", "gatsol_score")
        )
        r["thermostability_model_count"] = sum(
            math.isfinite(num(r.get(k))) for k in ("temberture_tm", "temstapro_t55_raw")
        )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="FASTA + PDB/CIF or structure directory -> ranked CSV"
    )
    p.add_argument(
        "--config",
        type=Path,
        help="JSON model paths; relative paths resolve against this file",
    )
    p.add_argument("--models", nargs="+", choices=list(MODEL_KEYS), required=True)
    p.add_argument(
        "--allow-partial",
        action="store_true",
        help="Exit 0 even if selected model results are missing",
    )
    p.add_argument("fasta", type=Path)
    p.add_argument(
        "structure_pos",
        nargs="?",
        type=Path,
        help="One PDB/CIF (single FASTA record) or structure directory",
    )
    p.add_argument(
        "--structures",
        "--structure",
        dest="structures",
        type=Path,
        help="One PDB/CIF or a directory of structures",
    )
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--device", choices=["cuda", "cpu"], default="cpu")
    p.add_argument("--threads", default="8")
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument(
        "--mask-batch-size",
        type=int,
        default=128,
        help="masked positions per ESMC/ESM3 forward batch (lower if GPU OOM)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=2400,
        help="per-model timeout in seconds; ESM3 is the slowest stage",
    )
    p.add_argument(
        "--esmc-model", default="esmc_300m", choices=["esmc_300m", "esmc_600m"]
    )
    p.add_argument(
        "--allow-model-download",
        action="store_true",
        help="Allow ESMC to download missing weights from Hugging Face",
    )
    p.add_argument(
        "--gatsol-checkpoint",
        type=Path,
        help="Optional GATSol best_model.pt/pkl override",
    )
    p.add_argument(
        "--masif-python",
        type=Path,
        help="Optional Masif environment Python executable for Pro4S",
    )
    p.add_argument(
        "--msms-bin",
        type=Path,
        help="MSMS executable (may be outside the MaSIF environment)",
    )
    p.add_argument(
        "--pdb2pqr-bin",
        type=Path,
        help="PDB2PQR executable (may be outside the MaSIF environment)",
    )
    p.add_argument(
        "--apbs-bin",
        type=Path,
        help="APBS executable (may be outside the MaSIF environment)",
    )
    p.add_argument(
        "--multivalue-bin",
        type=Path,
        help="APBS multivalue executable (may be outside the MaSIF environment)",
    )
    p.add_argument(
        "--netsolp-model-type",
        default="ESM1b",
        choices=["ESM1b", "ESM12", "Both", "Distilled"],
    )
    p.add_argument("--weights-json")
    a = p.parse_args(argv)
    global D, MODEL_ENV, SELECTED
    D, MODEL_ENV = load_config(a.config)
    SELECTED = set(a.models)
    for model in SELECTED:
        env = MODEL_ENV.setdefault(model, {})
        env.update(
            {
                "OMP_NUM_THREADS": str(a.threads),
                "MKL_NUM_THREADS": str(a.threads),
                "PYTHONUNBUFFERED": "1",
            }
        )
        if a.device == "cpu":
            env["CUDA_VISIBLE_DEVICES"] = ""
        if not a.allow_model_download:
            env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    for key in (
        "gatsol_checkpoint",
        "masif_python",
        "msms_bin",
        "pdb2pqr_bin",
        "apbs_bin",
        "multivalue_bin",
    ):
        if getattr(a, key) is not None:
            setattr(a, key, getattr(a, key).expanduser().resolve())
    if min(a.timeout, a.batch_size, a.mask_batch_size, int(a.threads)) <= 0:
        p.error("timeouts, batch sizes and threads must be positive")
    if a.structures is not None and a.structure_pos is not None:
        p.error(
            "provide the structure as a positional argument or --structures, not both"
        )
    a.structures = a.structures or a.structure_pos
    a.fasta, a.output = a.fasta.resolve(), a.output.resolve()
    a.structures = a.structures.resolve() if a.structures else None
    if a.output == a.fasta or a.output == a.structures:
        p.error("output must not overwrite an input")
    if a.structures is not None and not a.structures.exists():
        p.error(f"structure path does not exist: {a.structures}")
    records = fasta(a.fasta)
    if a.structures is not None and a.structures.is_file() and len(records) != 1:
        p.error(
            "a single PDB/CIF can only be used with exactly one FASTA record; use a structure directory for multiple records"
        )
    for ident, _ in records:
        if structure_for(ident, a.structures) == a.output:
            p.error("output must not overwrite a structure input")
    score_rows([], a.weights_json)  # validate before launching models
    with tempfile.TemporaryDirectory(prefix="prowet_") as td:
        work = Path(td)
        a.fasta = work / "input.fasta"
        a.fasta.write_text("".join(f">{ident}\n{seq}\n" for ident, seq in records))
        models = sequence_models(a, work)
        for model in ("gatsol", "pro4s"):
            if model not in SELECTED:
                continue
            if a.structures is None:
                models[model] = {"status": "missing_structure", "rows": {}}
            elif a.device == "cpu":
                models[model] = {"status": "requires_cuda_upstream_adapter", "rows": {}}
            elif model == "gatsol":
                models[model] = gatsol(
                    records, a.structures, work, a.timeout, a.gatsol_checkpoint
                )
            else:
                models[model] = pro4s(
                    records,
                    a.structures,
                    work,
                    a.timeout,
                    a.masif_python,
                    a.msms_bin,
                    a.pdb2pqr_bin,
                    a.apbs_bin,
                    a.multivalue_bin,
                )
        evo = evoef2(records, a.structures, work, a.timeout)
        output = []
        for ident, seq in records:
            b = base(ident)
            get = (
                lambda m: models[m]["rows"].get(ident) or models[m]["rows"].get(b) or {}
            )
            n, t, s, r, ec, e3, g, p4 = (
                get(x)
                for x in (
                    "netsolp",
                    "temberture",
                    "temstapro",
                    "rp3net",
                    "esmc",
                    "esm3",
                    "gatsol",
                    "pro4s",
                )
            )
            ev = evo[ident]
            struct = structure_for(ident, a.structures)

            def row_status(model: str, result: dict[str, Any], value_key: str) -> str:
                global_status = models[model]["status"]
                if global_status != "ok":
                    return global_status
                return (
                    "ok"
                    if math.isfinite(num(result.get(value_key)))
                    else "error_no_result"
                )

            row = {
                "id": ident,
                "sequence": seq,
                "length": len(seq),
                "structure_file": str(struct or ""),
                "netsolp_status": row_status("netsolp", n, "predicted_solubility"),
                "netsolp_score": num(n.get("predicted_solubility")),
                "rp3net_status": row_status("rp3net", r, "score"),
                "rp3net_score": num(r.get("score")),
                "temberture_status": row_status("temberture", t, "tem_TM"),
                "temberture_tm": num(t.get("tem_TM")),
                "temberture_class_score": num(t.get("tem_SC")),
                "temstapro_status": row_status("temstapro", s, "t55_raw"),
                "temstapro_t40_raw": num(s.get("t40_raw")),
                "temstapro_t55_raw": num(s.get("t55_raw")),
                "temstapro_t65_raw": num(s.get("t65_raw")),
                "temstapro_t55_binary": s.get("t55_binary", ""),
                "esmc_status": row_status("esmc", ec, "perplexity"),
                "esmc_perplexity": num(ec.get("perplexity")),
                "esm3_status": row_status("esm3", e3, "perplexity"),
                "esm3_perplexity": num(e3.get("perplexity")),
                "gatsol_status": row_status("gatsol", g, "score"),
                "gatsol_score": num(g.get("score")),
                "pro4s_status": row_status("pro4s", p4, "score"),
                "pro4s_score": num(p4.get("score")),
                "evoef2_status": ev["status"],
                "evoef2_energy": ev["energy"],
            }
            output.append(row)
        score_rows(output, a.weights_json)
        output.sort(
            key=lambda r: (
                num(r.get("screening_score"))
                if math.isfinite(num(r.get("screening_score")))
                else -1
            ),
            reverse=True,
        )
        for i, r in enumerate(output, 1):
            r["rank"] = i
        fields = [
            "rank",
            "id",
            "sequence",
            "length",
            "structure_file",
            "netsolp_status",
            "netsolp_score",
            "rp3net_status",
            "rp3net_score",
            "temberture_status",
            "temberture_tm",
            "temberture_class_score",
            "temstapro_status",
            "temstapro_t40_raw",
            "temstapro_t55_raw",
            "temstapro_t65_raw",
            "temstapro_t55_binary",
            "esmc_status",
            "esmc_perplexity",
            "esm3_status",
            "esm3_perplexity",
            "gatsol_status",
            "gatsol_score",
            "pro4s_status",
            "pro4s_score",
            "evoef2_status",
            "evoef2_energy",
            "solubility_consensus",
            "solubility_consensus_norm",
            "solubility_model_count",
            "thermostability_consensus",
            "thermostability_consensus_norm",
            "thermostability_model_count",
            "ranking_model_count",
            "ranking_weight_coverage",
            "screening_score",
        ]
        fields += [
            x
            for x in (
                "netsolp_score_norm",
                "rp3net_score_norm",
                "pro4s_score_norm",
                "gatsol_score_norm",
                "temberture_tm_norm",
                "temstapro_t55_raw_norm",
                "esmc_perplexity_norm",
                "esm3_perplexity_norm",
                "evoef2_energy_norm",
            )
            if any(x in r for r in output)
        ]
        a.output.parent.mkdir(parents=True, exist_ok=True)
        with a.output.open("w", newline="") as h:
            csv.DictWriter(h, fieldnames=fields, extrasaction="ignore").writeheader()
            csv.DictWriter(h, fieldnames=fields, extrasaction="ignore").writerows(
                output
            )
    print(f"wrote {len(output)} rows: {a.output}")
    for k, v in models.items():
        print(f"{k}: {v['status']}")
    print(f"evoef2: {sum(v['status']=='ok' for v in evo.values())}/{len(evo)} parsed")
    incomplete = any(row[m + "_status"] != "ok" for row in output for m in SELECTED)
    return 0 if a.allow_partial or not incomplete else 2


if __name__ == "__main__":
    raise SystemExit(main())
