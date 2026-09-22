"""Public protein screening API."""

from pathlib import Path
import subprocess
import sys

__version__ = "0.1.0"


def screen(
    fasta,
    output,
    *,
    models,
    structures=None,
    config=None,
    device="cpu",
    allow_partial=False,
    timeout=2400,
):
    """Run isolated screening; return the output Path, raise on incomplete results.

    Each call has its own process and temporary files, including concurrent calls.
    A CalledProcessError with returncode=2 leaves a diagnostic CSV at output.
    """
    if not models or isinstance(models, str):
        raise ValueError("models must be a nonempty sequence of model names")
    cmd = [
        sys.executable,
        "-m",
        "prowet",
        "run",
        str(fasta),
        "-o",
        str(output),
        "--models",
        *models,
        "--device",
        device,
        "--timeout",
        str(timeout),
    ]
    if structures is not None:
        cmd += ["--structures", str(structures)]
    if config is not None:
        cmd += ["--config", str(config)]
    if allow_partial:
        cmd += ["--allow-partial"]
    subprocess.run(cmd, check=True)
    return Path(output).resolve()
