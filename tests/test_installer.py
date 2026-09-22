"""Installer contracts independent of network, conda and GPU."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('screen_install', ROOT / 'scripts/install.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class InstallerTests(unittest.TestCase):
    def test_vendor_integrity_and_notices(self):
        manifest = json.loads((ROOT / 'third_party/manifest.json').read_text())
        self.assertEqual(len(manifest), 6)
        for name, model in manifest.items():
            self.assertEqual(len(model['revision']), 40)
            self.assertTrue(any(f['path'] in ('LICENSE', 'LICENSE.md', 'LICENCE.md') for f in model['files']))
            for item in model['files']:
                self.assertEqual(install.digest(ROOT / 'third_party' / name / item['path']), item['sha256'])

    def test_modified_source_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'source', Path(tmp) / 'target'
            source.write_text('official')
            target.write_text('user edit')
            with self.assertRaises(ValueError):
                install.copy_verified(source, target, install.digest(source))
            self.assertEqual(target.read_text(), 'user edit')

    def test_manifest_cannot_escape_via_path_or_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root'
            root.mkdir()
            (root / 'link').symlink_to(Path(tmp), target_is_directory=True)
            for path in ('../escape', '/absolute', 'link/escape'):
                with self.assertRaises(ValueError):
                    install.safe_path(root, path)

    def test_sources_resume_and_temstapro_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = install.parse_args(['--prefix', tmp, '--models', 'temstapro,evoef2', '--stage', 'sources'])
            obj = install.Installer(args)
            obj.sources()
            obj.sources()
            self.assertIn('from_pretrained(model_path)', (Path(tmp) / 'compat/prottrans_models.py').read_text())
            self.assertIn("model_path+'/pytorch_model.bin'", (obj.models / 'TemStaPro/prottrans_models.py').read_text())

    def test_graphbolt_patch_is_narrow_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'dgl/graphbolt/__init__.py'
            path.parent.mkdir(parents=True)
            original = 'def load_graphbolt():\n    pass\n\nload_graphbolt()\n'
            path.write_text(original)
            install.patch_graphbolt(root)
            first = path.read_text()
            install.patch_graphbolt(root)
            self.assertEqual(path.read_text(), first)
            self.assertEqual(path.with_suffix('.py.screen-original').read_text(), original)
            path.write_text('unexpected version')
            with self.assertRaises(ValueError):
                install.patch_graphbolt(root)

    def test_failure_report_nonzero_and_preserves_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(install.Installer, 'sources', side_effect=ValueError('fixture failure')):
                self.assertEqual(install.main(['--prefix', tmp, '--models', 'evoef2', '--stage', 'sources']), 1)
            report = json.loads((Path(tmp) / 'install-report.json').read_text())
            self.assertEqual(report['stages']['sources'], 'incomplete')
            self.assertFalse(report['inference_verified'])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'precious').write_text('keep')
            with self.assertRaises(ValueError):
                install.main(['--prefix', tmp, '--stage', 'config'])
            self.assertEqual((Path(tmp) / 'precious').read_text(), 'keep')

    def test_external_archive_asset_integrity(self):
        import io
        import tarfile
        with tempfile.TemporaryDirectory() as tmp:
            obj = install.Installer(install.parse_args(['--prefix', tmp, '--models', 'evoef2']))
            payload = Path(tmp) / 'payload'
            payload.write_bytes(b'parameter table')
            obj.manifest['EvoEF2'] = {'repository': 'example/repo', 'revision': 'abc',
                'assets': [{'path': 'library/table', 'git_blob_sha1': install.digest(payload, git=True)}]}
            archive = Path(tmp) / 'downloads/EvoEF2-abc.tar.gz'
            archive.parent.mkdir()
            def write_archive(content):
                with tarfile.open(archive, 'w:gz') as tar:
                    item = tarfile.TarInfo('repo-abc/library/table')
                    item.size = len(content)
                    tar.addfile(item, io.BytesIO(content))
            write_archive(payload.read_bytes())
            with patch.object(install, 'download'):
                obj.assets('EvoEF2')
                self.assertEqual((obj.models / 'EvoEF2/library/table').read_bytes(), payload.read_bytes())
                (obj.models / 'EvoEF2/library/table').unlink()
                write_archive(b'corrupt')
                with self.assertRaises(ValueError):
                    obj.assets('EvoEF2')
                self.assertFalse((obj.models / 'EvoEF2/library/table').exists())

    def test_plan_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'new'
            self.assertEqual(install.main(['--prefix', str(target), '--plan']), 0)
            self.assertFalse(target.exists())

    def test_config_shell_quoting_and_routing(self):
        with tempfile.TemporaryDirectory(prefix="screen ' $ ") as tmp:
            obj = install.Installer(install.parse_args(['--prefix', tmp, '--models', 'evoef2']))
            obj.config()
            # Fake interpreter records argv; no command substitution from paths.
            obj.py.parent.mkdir(parents=True)
            obj.py.write_text('#!/usr/bin/env python3\nimport sys,json; print(json.dumps(sys.argv[1:]))\n')
            obj.py.chmod(0o755)
            launcher = obj.root / 'bin/screen'
            args = json.loads(subprocess.check_output([str(launcher), 'run', 'input with spaces', '--models', 'evoef2'], text=True))
            self.assertEqual(args[:4], ['-m', 'prowet', 'run', '--config'])
            self.assertIn('input with spaces', args)
            self.assertIn('--apbs-bin', args)
            args = json.loads(subprocess.check_output([str(launcher), 'doctor'], text=True))
            self.assertNotIn('--apbs-bin', args)


if __name__ == '__main__':
    unittest.main()
