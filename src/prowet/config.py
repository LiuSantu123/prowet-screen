"""Portable, explicit model installations. No checkpoints are distributed."""

import json
import os
import sys
from pathlib import Path

MODEL_KEYS = {
    "netsolp": ("netsolp_py", "netsolp", "netsolp_models"),
    "rp3net": ("rp3net_py", "rp3_src", "rp3_repo", "rp3_ckpt"),
    "temberture": ("temberture_py", "temberture_run", "temberture_models"),
    "temstapro": ("temstapro_py", "temstapro", "temstapro_dir", "prottrans"),
    "esmc": ("esmc_py", "esmc_run"),
    "esm3": ("esm3_py", "esm3_run"),
    "gatsol": ("gatsol_py", "gatsol_repo", "gatsol_ckpt"),
    "pro4s": ("pro4s_py", "pro4s_root", "masif_py"),
    "evoef2": ("evoef2",),
}


def load_config(path=None):
    keys = {k for items in MODEL_KEYS.values() for k in items}
    missing = Path("/__prowet_unconfigured__")
    defaults = {k: missing / k for k in keys}
    defaults.update(
        {k: Path(sys.executable) for k in keys if k.endswith("_py") and k != "masif_py"}
    )
    runners = Path(__file__).parent / "runners"
    defaults.update(
        {
            name + "_run": runners / (name + ".py")
            for name in ("esmc", "esm3", "temberture")
        }
    )
    if path is None:
        return defaults, {}
    path = Path(path).resolve()
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) - {"paths", "env"}:
        raise ValueError("config supports only paths and env objects")
    paths, env = data.get("paths", {}), data.get("env", {})
    if not isinstance(paths, dict) or set(paths) - keys:
        raise ValueError("unknown model path key in config")
    for key, value in paths.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a nonempty path string")
        target = Path(os.path.expandvars(value)).expanduser()
        defaults[key] = (
            (path.parent / target).absolute() if not target.is_absolute() else target
        )
    if not isinstance(env, dict) or set(env) - set(MODEL_KEYS):
        raise ValueError("env must map known model names to environment variables")
    for model, values in env.items():
        if not isinstance(values, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()
        ):
            raise ValueError(f"env.{model} must map strings to strings")
        env[model] = {
            k: os.path.expandvars(os.path.expanduser(v)) for k, v in values.items()
        }
    return defaults, env
