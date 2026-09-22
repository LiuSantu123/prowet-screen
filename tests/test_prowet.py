import csv
import io
import json
import math
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from prowet import engine, screen
from prowet.config import load_config


class ScreeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "prowet", *map(str, args)],
            capture_output=True,
            text=True,
        )

    def test_fasta_rejects_unsafe_duplicate_empty_and_noncanonical(self):
        for text in (
            ">../a\nAAA\n",
            ">x\nAAA\n>x\nAAA\n",
            ">\nAAA\n",
            "AAA\n>x\nAAA",
            ">x\nABX\n",
            ">x\n",
        ):
            with self.subTest(text=text):
                path = self.root / "input.fa"
                path.write_text(text)
                with self.assertRaises(ValueError):
                    engine.fasta(path)

    def test_fasta_normalizes_case_and_whitespace(self):
        path = self.root / "input.fa"
        path.write_text(">a description\na c\nDE\n")
        self.assertEqual(engine.fasta(path), [("a", "ACDE")])

    def test_exact_structure_matching(self):
        (self.root / "a10.pdb").touch()
        self.assertIsNone(engine.structure_for("a1", self.root))
        (self.root / "a1.pdb").touch()
        self.assertEqual(engine.structure_for("a1", self.root).name, "a1.pdb")
        (self.root / "a1.cif").touch()
        with self.assertRaises(ValueError):
            engine.structure_for("a1", self.root)

    def test_ranking_missing_values_direction_and_ties(self):
        rows = [
            dict(netsolp_score=0.9, evoef2_energy=-50),
            dict(netsolp_score=0.1, evoef2_energy=-10),
            dict(netsolp_score=0.1),
        ]
        engine.score_rows(rows, None)
        self.assertGreater(rows[0]["screening_score"], rows[1]["screening_score"])
        self.assertEqual(rows[1]["netsolp_score_norm"], rows[2]["netsolp_score_norm"])
        self.assertEqual(rows[2]["ranking_model_count"], 1)
        self.assertTrue(math.isnan(rows[2]["evoef2_energy_norm"]))
        single = [dict(netsolp_score=0.9)]
        engine.score_rows(single, None)
        self.assertEqual(single[0]["screening_score"], 0.5)
        empty = [{}]
        engine.score_rows(empty, None)
        self.assertTrue(math.isnan(empty[0]["screening_score"]))

    def test_partial_rows_are_detected(self):
        script = self.root / "predict.py"
        script.write_text(
            'import sys\np=sys.argv[sys.argv.index("--OUTPUT_PATH")+1]\nopen(p,"w").write("id,predicted_solubility\\na,0.8\\n")\n'
        )
        config = self.root / "config.json"
        config.write_text(
            json.dumps(
                {"paths": {"netsolp": str(script), "netsolp_models": str(self.root)}}
            )
        )
        fasta = self.root / "in.fa"
        fasta.write_text(">a\nACDE\n>b\nACDF\n")
        out = self.root / "out.csv"
        result = self.cli(
            "run", fasta, "--config", config, "--models", "netsolp", "-o", out
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        rows = {r["id"]: r for r in csv.DictReader(io.StringIO(out.read_text()))}
        self.assertEqual(rows["a"]["netsolp_status"], "ok")
        self.assertEqual(rows["b"]["netsolp_status"], "error_no_result")

    def test_weights_validate(self):
        path = self.root / "w.json"
        for value in ({"typo": 1}, {"netsolp_score": -1}, {"netsolp_score": "bad"}, []):
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                engine.score_rows([], str(path))

    def test_config_relative_to_file_and_unknown_keys(self):
        path = self.root / "config.json"
        path.write_text('{"paths":{"evoef2":"tools/EvoEF2"}}')
        config, _ = load_config(path)
        self.assertEqual(config["evoef2"], self.root / "tools/EvoEF2")
        path.write_text('{"paths":{"evov2":"foo"}}')
        with self.assertRaises(ValueError):
            load_config(path)

    def test_missing_model_fails_but_writes_diagnostic_csv(self):
        path = self.root / "in.fa"
        path.write_text(">a\nACDE\n")
        out = self.root / "out.csv"
        result = self.cli("run", path, "-o", out, "--models", "netsolp")
        self.assertEqual(result.returncode, 2, result.stderr)
        row = list(csv.DictReader(io.StringIO(out.read_text())))[0]
        self.assertIn("missing", row["netsolp_status"])
        self.assertEqual(row["rp3net_status"], "not_selected")
        self.assertTrue(math.isnan(float(row["screening_score"])))
        result = self.cli(
            "run", path, "-o", out, "--models", "netsolp", "--allow-partial"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_subprocess_adapter_contract(self):
        # A stub tests invocation/parsing only; it is not a model validation.
        script = self.root / "predict.py"
        script.write_text(
            'import sys,csv\np=sys.argv[sys.argv.index("--OUTPUT_PATH")+1]\nwith open(p,"w") as f:\n w=csv.writer(f);w.writerow(["id","predicted_solubility"]);w.writerow(["a",0.8])\n'
        )
        config = self.root / "config.json"
        config.write_text(
            json.dumps(
                {"paths": {"netsolp": str(script), "netsolp_models": str(self.root)}}
            )
        )
        fasta = self.root / "in.fa"
        fasta.write_text(">a\nACDE\n")
        out = self.root / "out.csv"
        screen(fasta, out, models=["netsolp"], config=config)
        row = list(csv.DictReader(io.StringIO(out.read_text())))[0]
        self.assertEqual(row["netsolp_status"], "ok")
        self.assertEqual(float(row["netsolp_score"]), 0.8)

    def test_run_reports_exit_error_and_timeout(self):
        result = engine.run(
            [Path(sys.executable), "-c", "raise SystemExit(3)"], self.root, None, 5
        )
        self.assertTrue(result["status"].startswith("error_exit_3"))
        result = engine.run(
            [Path(sys.executable), "-c", "import time;time.sleep(10)"],
            self.root,
            None,
            1,
        )
        self.assertEqual(result["status"], "timeout_1s")

    def test_rank_ignores_failed_model_score(self):
        inp = self.root / "in.csv"
        inp.write_text("id,netsolp_status,netsolp_score\na,error,0.99\nb,ok,0.1\n")
        out = self.root / "out.csv"
        result = self.cli("rank", inp, "-o", out)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = list(csv.DictReader(io.StringIO(out.read_text())))
        self.assertEqual(rows[0]["id"], "b")
        self.assertTrue(math.isnan(float(rows[1]["screening_score"])))

    def test_checkpoint_archive_rejects_escape_and_symlinks(self):
        for name, kind in (
            ("../escape.pt", tarfile.REGTYPE),
            ("link.pt", tarfile.SYMTYPE),
        ):
            path = self.root / "bad.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.linkname = "/tmp/outside"
                archive.addfile(info)
            destination = self.root / "unpack"
            destination.mkdir(exist_ok=True)
            with self.assertRaises(ValueError):
                engine.extract_checkpoint_archive(path, destination)

    def test_checkpoint_archive_accepts_regular_weights(self):
        path = self.root / "good.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            info = tarfile.TarInfo("./weights/best_model.pt")
            info.size = 3
            archive.addfile(info, io.BytesIO(b"abc"))
        destination = self.root / "unpack"
        destination.mkdir()
        engine.extract_checkpoint_archive(path, destination)
        self.assertEqual((destination / "weights/best_model.pt").read_bytes(), b"abc")

    def test_structure_sequence_identity(self):
        import gemmi

        st = gemmi.Structure()
        model = gemmi.Model("1")
        chain = gemmi.Chain("A")
        for i, name in enumerate(["GLY", "ALA", "CYS", "ASP"], 1):
            r = gemmi.Residue()
            r.name = name
            r.seqid = gemmi.SeqId(i, " ")
            atom = gemmi.Atom()
            atom.name = "CA"
            atom.element = gemmi.Element("C")
            atom.pos = gemmi.Position(i * 3.8, 0, 0)
            r.add_atom(atom)
            chain.add_residue(r)
        model.add_chain(chain)
        st.add_model(model)
        for suffix in ("pdb", "cif"):
            path = self.root / ("in." + suffix)
            if suffix == "pdb":
                st.write_pdb(str(path))
            else:
                st.make_mmcif_document().write_file(str(path))
            out = self.root / "matched.pdb"
            engine.write_sequence_matched_pdb(path, "ACD", out)
            self.assertEqual(len(gemmi.read_structure(str(out))[0][0]), 3)
            with self.assertRaises(ValueError):
                engine.write_sequence_matched_pdb(path, "DDD", out)


if __name__ == "__main__":
    unittest.main()
