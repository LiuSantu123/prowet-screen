import argparse
import csv
import json
import sys
from pathlib import Path
from . import __version__
from .config import MODEL_KEYS, load_config


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "run":
        from .engine import main as run

        try:
            return run(argv[1:])
        except (ValueError, OSError) as exc:
            print(f"prowet: {exc}", file=sys.stderr)
            return 2
    p = argparse.ArgumentParser(
        description="Configurable protein sequence/structure screening"
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="Run selected models (run --help for options)")
    doctor = sub.add_parser(
        "doctor", help="Check configured paths, not model inference"
    )
    doctor.add_argument("--config", type=Path)
    doctor.add_argument(
        "--models", nargs="+", choices=list(MODEL_KEYS), default=list(MODEL_KEYS)
    )
    rank = sub.add_parser(
        "rank", help="Rank an existing model-score CSV without model installations"
    )
    rank.add_argument("input", type=Path)
    rank.add_argument("-o", "--output", required=True, type=Path)
    rank.add_argument("--weights-json")
    a = p.parse_args(argv)
    try:
        if a.command == "doctor":
            paths, _ = load_config(a.config)
            result = {
                m: {
                    k: {"path": str(paths[k]), "exists": paths[k].exists()}
                    for k in MODEL_KEYS[m]
                }
                for m in a.models
            }
            print(json.dumps(result, indent=2))
            return (
                0
                if all(x["exists"] for v in result.values() for x in v.values())
                else 2
            )
        from .engine import score_rows, num
        import math

        if a.input.resolve() == a.output.resolve():
            raise ValueError("output must differ from input")
        with a.input.open(newline="") as f:
            rows = list(csv.DictReader(f))
        if (
            not rows
            or any(not row.get("id") for row in rows)
            or len({r["id"] for r in rows}) != len(rows)
        ):
            raise ValueError("input must contain nonempty unique id values")
        # Scores from failed adapters never contribute to a ranking.
        for row in rows:
            for key in list(row):
                model = key.split("_", 1)[0]
                if (
                    model + "_status" in row
                    and row[model + "_status"] != "ok"
                    and key != model + "_status"
                ):
                    row[key] = math.nan
        score_rows(rows, a.weights_json)
        rows.sort(
            key=lambda r: (
                num(r["screening_score"])
                if math.isfinite(num(r["screening_score"]))
                else -1
            ),
            reverse=True,
        )
        for i, row in enumerate(rows, 1):
            row["rank"] = i
        fields = list(dict.fromkeys(k for row in rows for k in row))
        a.output.parent.mkdir(parents=True, exist_ok=True)
        with a.output.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} rows: {a.output}")
        return 0
    except (ValueError, OSError) as exc:
        print(f"prowet: {exc}", file=sys.stderr)
        return 2
