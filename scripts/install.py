#!/usr/bin/env python3
"""Resumable, isolated Linux cluster installer (standard-library controller)."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
NAMES = {'netsolp': 'NetSolP', 'rp3net': 'RP3Net', 'temberture': 'TemBERTure',
         'temstapro': 'TemStaPro', 'gatsol': 'GATSol', 'evoef2': 'EvoEF2',
         'pro4s': 'Pro4S', 'esmc': 'ESMC', 'esm3': 'ESM3'}
PRO4S_REV = 'fcf210d796e4b2be308686eb913b51133e15cd00'


def shell_join(args):
    return " ".join(shlex.quote(str(arg)) for arg in args)


def run(args, **kwargs):
    print('+', shell_join([str(x) for x in args]), flush=True)
    subprocess.run([str(x) for x in args], check=True, **kwargs)


def digest(path, git=False):
    h = hashlib.sha1() if git else hashlib.sha256()
    if git:
        h.update(b'blob ' + str(path.stat().st_size).encode() + b'\0')
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_path(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or root.resolve() not in (path.resolve(), *path.resolve().parents):
        raise ValueError('Unsafe manifest path: ' + relative)
    return path


def download(url, destination, expected=None, git=False, headers=()):
    if destination.is_file() and destination.stat().st_size and (expected is None or digest(destination, git) == expected):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.part')
    # curl retries transport failures; final filenames appear only after validation.
    run(['curl', '-fL', '--retry', '3', '--connect-timeout', '30', '--speed-limit', '1024', '--speed-time', '60', *[arg for h in headers for arg in ('-H', h)], url, '-o', partial])
    if expected and digest(partial, git) != expected:
        raise ValueError('Checksum mismatch: ' + str(partial))
    if not partial.stat().st_size:
        raise ValueError('Empty download: ' + url)
    partial.replace(destination)


def copy_verified(source, target, expected):
    if digest(source) != expected:
        raise ValueError('Bundled source checksum mismatch: ' + str(source))
    if target.exists():
        if not target.is_file() or digest(target) != expected:
            raise ValueError('Refusing to overwrite modified source: ' + str(target))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def patch_graphbolt(site):
    """DGL 2.1 GraphBolt is unused by these inference paths; skip its ABI loader."""
    path = site / 'dgl/graphbolt/__init__.py'
    marker = '# protein-screen: GraphBolt not used; Torch 2.5 has no DGL 2.1 binary'
    value = path.read_text()
    if marker in value:
        return
    old = '\nload_graphbolt()\n'
    if value.count(old) != 1:
        raise ValueError('Unexpected DGL loader; refusing broad patch')
    path.with_suffix('.py.screen-original').write_text(value)
    path.write_text(value.replace(old, '\n' + marker + '\n# load_graphbolt()\n'))


class Installer:
    def __init__(self, args):
        self.a = args
        self.root = args.prefix.resolve()
        self.models = self.root / 'models'
        self.core = self.root / 'envs/screen2'
        self.masif = self.root / 'envs/masif'
        self.py = self.core / 'bin/python'
        self.sdk = self.root / 'esm-sdk-3.1.1'
        self.hf = self.root / 'cache/huggingface/hub'
        self.torch = self.root / 'cache/torch'
        self.manifest = json.loads((REPO / 'third_party/manifest.json').read_text())
        self.errors = []

    def sources(self):
        for model in self.a.models:
            name = NAMES[model]
            if name in self.manifest:
                for item in self.manifest[name]['files']:
                    copy_verified(safe_path(REPO / 'third_party' / name, item['path']),
                                  safe_path(self.models / name, item['path']), item['sha256'])
            elif model == 'pro4s':
                target = self.models / name
                if target.exists():
                    actual = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
                    dirty = subprocess.check_output(['git', '-C', str(target), 'status', '--porcelain', '--untracked-files=no'], text=True)
                    if actual != PRO4S_REV or dirty:
                        raise ValueError('Existing Pro4S checkout differs; use another prefix')
                else:
                    partial = target.with_name('Pro4S.fetch')
                    if partial.exists():
                        raise ValueError('Interrupted Pro4S clone exists; inspect/rename ' + str(partial))
                    partial.mkdir(parents=True)
                    run(['git', 'init', partial])
                    run(['git', '-C', partial, 'remote', 'add', 'origin', 'https://github.com/TEKHOO/Pro4S.git'])
                    run(['git', '-C', partial, 'fetch', '--depth', '1', 'origin', PRO4S_REV])
                    run(['git', '-C', partial, 'checkout', '--detach', 'FETCH_HEAD'])
                    partial.rename(target)
        if 'temstapro' in self.a.models:
            from prepare_temstapro_compat import prepare
            if not (self.root / 'compat/temstapro').exists():
                prepare(self.models / 'TemStaPro', self.root / 'compat')

    def create_env(self, path, packages):
        if (path / 'conda-meta/history').exists():
            run([self.a.conda, 'install', '-y', '--override-channels', '-c', 'conda-forge', '-c', 'bioconda', '-p', path, *packages])
        if not (path / 'conda-meta/history').exists():
            if path.exists():
                raise ValueError('Refusing to adopt non-conda directory: ' + str(path))
            run([self.a.conda, 'create', '-y', '--override-channels', '-c', 'conda-forge', '-c', 'bioconda', '-p', path, *packages])

    def envs(self):
        modern = any(m != 'evoef2' for m in self.a.models)
        core_packages = ['python=3.10', 'pip', 'cxx-compiler', 'make']
        if modern:
            core_packages += ['numpy=1.26.4', 'matplotlib-base=3.4.3']
        self.create_env(self.core, core_packages)
        if modern:
            run([self.py, '-m', 'pip', 'install', '-r', REPO / 'envs/fresh-core-requirements.txt'])
            run([self.py, '-m', 'pip', 'install', '--only-binary=:all:', '--no-index',
                 '-f', 'https://data.pyg.org/whl/torch-2.5.0+cu118.html',
                 'torch-scatter', 'torch-sparse', 'torch-cluster', 'torch-spline-conv'])
            site = Path(subprocess.check_output([str(self.py), '-c', 'import sysconfig; print(sysconfig.get_paths()["purelib"])'], text=True).strip())
            patch_graphbolt(site)
            run([self.py, '-m', 'pip', 'install', '--no-deps', '--upgrade', '--target', self.sdk, 'esm==3.1.1'])
        run([self.py, '-m', 'pip', 'install', REPO])
        if 'rp3net' in self.a.models:
            run([self.py, '-m', 'pip', 'install', '--no-deps', self.models / 'RP3Net'])
        if 'evoef2' in self.a.models:
            cpp = sorted((self.models / 'EvoEF2/src').glob('*.cpp'))
            if not cpp:
                raise ValueError('Run sources stage before envs')
            compiler = self.core / 'bin/x86_64-conda-linux-gnu-c++'
            run([self.a.conda, 'run', '-p', self.core, compiler, '-O3', '-ffast-math', '-Wl,-rpath,' + str(self.core / 'lib'), '-o',
                 self.models / 'EvoEF2/EvoEF2', *cpp])
        if 'pro4s' in self.a.models:
            self.create_env(self.masif, ['python=3.7', 'pip<24.1', 'libstdcxx-ng', 'libgomp', 'libgl', 'apbs=1.5', 'msms=2.6.1'])
            run([self.masif / 'bin/python', '-m', 'pip', 'install', '-r', REPO / 'envs/fresh-masif-requirements.txt'])
            wheel = self.root / 'downloads/pymesh2-0.3-cp37-cp37m-linux_x86_64.whl'
            download('https://api.github.com/repos/PyMesh/PyMesh/releases/assets/22449980',
                     wheel, 'da1f2df6c6856f58cf537cb877aae420108d4ac34d2a78bb47769cdcf2a85980',
                     headers=('Accept: application/octet-stream',))
            run([self.masif / 'bin/python', '-m', 'pip', 'install', '--no-deps', wheel])
            self.build_multivalue()
            self.build_reduce()
        run([self.py, '-m', 'pip', 'check'])

    def build_reduce(self):
        # MaSIF calls reduce through PATH; do not inherit a hidden Amber install.
        import tarfile
        revision = 'd723303c0ae7a9991a4f723b74f9bfa268d33e87'
        archive = self.root / 'downloads/reduce.tar.gz'
        download('https://codeload.github.com/rlabduke/reduce/tar.gz/' + revision, archive,
                 '1edda3d93dadfb9d70816d0fe24f8447c26723f35d813cce60367a5b16da4131')
        source = self.root / 'build/reduce'
        with tarfile.open(archive) as tar:
            for member in tar:
                relative = Path(member.name).relative_to('reduce-' + revision)
                target = safe_path(source, str(relative))
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    content = tar.extractfile(member).read()
                    if target.exists() and target.read_bytes() != content:
                        raise ValueError('Refusing modified Reduce source: ' + str(target))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                else:
                    raise ValueError('Unsupported archive entry: ' + member.name)
        cxx = shell_join([self.core / 'bin/x86_64-conda-linux-gnu-c++', '-Wl,-rpath,' + str(self.core / 'lib')])
        for directory in ('toolclasses', 'libpdb', 'reduce_src'):
            run([self.a.conda, 'run', '-p', self.core, 'make', '-C', source / directory,
                 'CXX=' + cxx, 'CC=' + shell_join([self.core / 'bin/x86_64-conda-linux-gnu-cc']),
                 'DICT_HOME=' + str(source / 'reduce_wwPDB_het_dict.txt'), 'all'])
        shutil.copy2(source / 'reduce_src/reduce', self.masif / 'bin/reduce')

    def build_multivalue(self):
        # The conda APBS 1.5 package ships the source but omits this executable
        # and its generated apbscfg.h. No optional solver/MPI feature is needed.
        build = self.root / 'build/multivalue'
        build.mkdir(parents=True, exist_ok=True)
        (build / 'apbscfg.h').write_text('/* Standalone multivalue: no optional APBS solvers or MPI. */\n#define PACKAGE_STRING "APBS 1.5"\n')
        source = self.masif / 'share/apbs/tools/mesh/multivalue.c'
        if digest(source, git=True) != '62e17d5a604487d74fca632ee2c34727f021b699':
            raise ValueError('Unexpected APBS multivalue source; inspect before building')
        run([self.a.conda, 'run', '-p', self.core, self.core / 'bin/x86_64-conda-linux-gnu-cc',
             '-std=gnu99', '-O2', '-I', self.masif / 'include', '-I', self.masif / 'include/apbs',
             '-I', build, source, '-L', self.masif / 'lib',
             '-Wl,--disable-new-dtags', '-Wl,-rpath,' + str(self.masif / 'lib'),
             '-lapbs_mg', '-lapbs_generic', '-lapbs_pmgc', '-lmaloc', '-lm',
             '-o', self.masif / 'bin/multivalue'])

    def snapshot(self, repo_id, local=None):
        # HF records the resolved revision in its cache, supports resumable transfers,
        # and uses HF_TOKEN from the environment without writing it to config or logs.
        script = ('from huggingface_hub import snapshot_download; import sys; '
                  'print(snapshot_download(repo_id=sys.argv[1],cache_dir=sys.argv[2],'
                  'local_dir=sys.argv[3] or None))')
        run([self.py, '-c', script, repo_id, self.hf, local or ''])

    def assets(self, name):
        import tarfile
        spec = self.manifest[name]
        missing = [item for item in spec['assets']
                   if not (safe_path(self.models / name, item['path']).is_file()
                           and digest(safe_path(self.models / name, item['path']), git=True) == item['git_blob_sha1'])]
        if not missing:
            return
        archive = self.root / 'downloads' / (name + '-' + spec['revision'] + '.tar.gz')
        download('https://codeload.github.com/' + spec['repository'] + '/tar.gz/' + spec['revision'], archive)
        with tarfile.open(archive) as tar:
            members = {m.name.split('/', 1)[1]: m for m in tar.getmembers() if '/' in m.name and m.isfile()}
            for item in missing:
                target = safe_path(self.models / name, item['path'])
                target.parent.mkdir(parents=True, exist_ok=True)
                partial = target.with_name(target.name + '.part')
                with tar.extractfile(members[item['path']]) as src, partial.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
                if digest(partial, git=True) != item['git_blob_sha1']:
                    raise ValueError('Upstream asset checksum mismatch: ' + item['path'])
                partial.replace(target)

    def weights_one(self, model):
        name = NAMES[model]
        if name in self.manifest:
            self.assets(name)
        if model == 'netsolp':
            if self.a.netsolp_models:
                for source in self.a.netsolp_models.resolve().iterdir():
                    if source.is_file() and source.suffix in ('.onnx', '.pkl'):
                        copy_verified(source, self.models / name / 'PredictionServer/models' / source.name, digest(source))
            if not all((self.models / name / 'PredictionServer/models' / f'Solubility_ESM1b_{i}_quantized.onnx').is_file() for i in range(5)):
                raise ValueError('NetSolP: obtain models from https://services.healthtech.dtu.dk/service.php?NetSolP and rerun with --netsolp-models DIR')
        elif model == 'rp3net':
            download('https://ftp.ebi.ac.uk/pub/software/RP3Net/v0.1/checkpoints/rp3net_v0.1_d.ckpt',
                     self.models / name / 'weights/rp3net_v0.1_d.ckpt')
        elif model == 'temberture':
            self.snapshot('Rostlab/prot_bert_bfd', self.root / 'prot_bert_bfd')
        elif model == 'temstapro':
            self.snapshot('Rostlab/prot_t5_xl_half_uniref50-enc', self.models / name / 'ProtTrans')
        elif model == 'esmc':
            self.snapshot('EvolutionaryScale/esmc-600m-2024-12')
            self.snapshot('EvolutionaryScale/esmc-300m-2024-12')
        elif model == 'esm3':
            self.snapshot('EvolutionaryScale/esm3-sm-open-v1')
        elif model == 'gatsol':
            target = self.models / name / 'check_point/best_model/best_model.tar.gz'
            if self.a.gatsol_checkpoint:
                copy_verified(self.a.gatsol_checkpoint, target, digest(self.a.gatsol_checkpoint))
            elif not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                partial = target.with_suffix('.part')
                run([self.py, '-m', 'gdown', '1MnR2wv3MGBT0CKeHHUTErx7eYQVkC-c4', '-O', partial])
                # Reject Google Drive quota/HTML responses before marking complete.
                import tarfile
                with tarfile.open(partial) as archive:
                    if not any(m.isfile() for m in archive.getmembers()):
                        raise ValueError('Empty GATSol checkpoint archive')
                partial.replace(target)
            self.esm_weights('esm1b_t33_650M_UR50S')
        elif model == 'pro4s':
            target = self.models / name / 'checkpoints/finetune.ckpt'
            if self.a.pro4s_checkpoint:
                copy_verified(self.a.pro4s_checkpoint, target, digest(self.a.pro4s_checkpoint))
            elif not target.exists():
                run([self.py, '-c', 'from huggingface_hub import hf_hub_download; import sys; hf_hub_download("qj666/Pro4S", "finetune.ckpt", local_dir=sys.argv[1])', target.parent])
            self.esm_weights('esm2_t36_3B_UR50D')

    def esm_weights(self, model):
        for suffix in ('', '-contact-regression'):
            filename = model + suffix + '.pt'
            folder = 'regression' if suffix else 'models'
            download('https://dl.fbaipublicfiles.com/fair-esm/' + folder + '/' + filename,
                     self.torch / 'hub/checkpoints' / filename)

    def weights(self):
        for model in self.a.models:
            try:
                self.weights_one(model)
            except Exception as error:
                self.errors.append('weights/' + model + ': ' + str(error))
                print(self.errors[-1], file=sys.stderr, flush=True)

    def config(self):
        variables = {'SCREEN_CORE_PREFIX': self.core, 'SCREEN_MASIF_PREFIX': self.masif,
                     'SCREEN_MODELS': self.models, 'SCREEN_COMPAT': self.root / 'compat',
                     'SCREEN_ESM_SDK': self.sdk, 'SCREEN_HF_CACHE': self.hf,
                     'SCREEN_PROTBERT': self.root / 'prot_bert_bfd'}
        import string
        config = json.loads(string.Template((REPO / 'examples/config.screen2.json').read_text()).substitute(
            {k: str(v).replace('\\', '\\\\').replace('"', '\\"') for k, v in variables.items()}))
        for model in NAMES:
            config['env'].setdefault(model, {}).update({'HF_HUB_CACHE': str(self.hf), 'TORCH_HOME': str(self.torch)})
        (self.root / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
        # Prefix-specific executable needs neither shell activation nor exported variables.
        options = []
        for flag in ('msms_bin', 'apbs_bin', 'multivalue_bin'):
            path = getattr(self.a, flag) or self.masif / 'bin' / flag[:-4]
            if path:
                options += ['--' + flag.replace('_', '-'), str(path.resolve())]
        options += ['--pdb2pqr-bin', str(self.core / 'bin/pdb2pqr')]
        launcher = self.root / 'bin/screen'
        launcher.parent.mkdir(exist_ok=True)
        launcher.write_text('#!/usr/bin/env bash\nset -euo pipefail\ncommand=${1:-}\n'
            'if [[ "$command" == run || "$command" == doctor ]]; then\n  shift\n'
            '  extra=()\n  if [[ "$command" == run ]]; then extra=(' + shell_join(options) + '); fi\n'
            '  exec ' + shlex.quote(str(self.py)) + ' -m protein_screen "$command" --config '
            + shlex.quote(str(self.root / 'config.json')) + ' "${extra[@]}" "$@"\nfi\nexec '
            + shlex.quote(str(self.py)) + ' -m protein_screen "$@"\n')
        launcher.chmod(0o755)
        (self.root / 'activate.sh').write_text('export PATH=' + shlex.quote(str(self.root / 'bin')) + ':"$PATH"\n')

    def check(self):
        run([self.py, '-m', 'pip', 'check'])
        run([self.root / 'bin/screen', 'doctor', '--models', *self.a.models])
        if any(m != 'evoef2' for m in self.a.models):
            run([self.py, '-c', 'import torch, transformers, adapters, dgl, torch_geometric, torch_scatter, torch_sparse, onnxruntime, iFeatureOmegaCLI; print(torch.__version__, transformers.__version__)'])
            sdk_env = dict(os.environ, PYTHONPATH=str(self.sdk))
            run([self.py, '-c', 'from esm.models.esmc import ESMC; from esm.models.esm3 import ESM3; print("ESM SDK imports OK")'], env=sdk_env)
        if 'pro4s' in self.a.models:
            if not (self.masif / 'bin/reduce').is_file():
                self.errors.append('Missing MaSIF reduce executable; rerun envs stage')
            run([self.masif / 'bin/python', '-c', 'import pymesh, sklearn, Bio, open3d; m=pymesh.form_mesh([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]],[[0,1,2]]); print(m.num_vertices)'])
            for flag in ('msms_bin', 'apbs_bin', 'multivalue_bin'):
                path = getattr(self.a, flag) or self.masif / 'bin' / flag[:-4]
                if not path or not path.is_file() or not os.access(path, os.X_OK):
                    self.errors.append('Pro4S native tool missing: --' + flag.replace('_', '-') + ' PATH (see docs/install_zh.md)')
        required = {
            'netsolp': [self.models / 'NetSolP/PredictionServer/models' / f'Solubility_ESM1b_{i}_quantized.onnx' for i in range(5)],
            'rp3net': [self.models / 'RP3Net/weights/rp3net_v0.1_d.ckpt'],
            'temberture': [self.root / 'prot_bert_bfd/config.json'],
            'temstapro': [self.models / 'TemStaPro/ProtTrans/config.json'],
            'gatsol': [self.models / 'GATSol/check_point/best_model/best_model.tar.gz', self.torch / 'hub/checkpoints/esm1b_t33_650M_UR50S.pt'],
            'pro4s': [self.models / 'Pro4S/checkpoints/finetune.ckpt', self.torch / 'hub/checkpoints/esm2_t36_3B_UR50D.pt'],
        }
        for model in self.a.models:
            name = NAMES[model]
            paths = required.get(model, [])
            if name in self.manifest:
                paths = paths + [self.models / name / a['path'] for a in self.manifest[name]['assets']]
            for path in paths:
                if not path.is_file() or not path.stat().st_size:
                    self.errors.append('Missing asset: ' + str(path))
            if model in ('esmc', 'esm3'):
                pattern = 'models--*--esm3-sm-open-v1/snapshots/*/data/weights/esm3_sm_open_v1.pth' if model == 'esm3' else 'models--*--esmc-600m-2024-12/snapshots/*/data/weights/esmc_600m_2024_12_v0.pth'
                if not any(p.is_file() and p.stat().st_size for p in self.hf.glob(pattern)):
                    self.errors.append('Missing HF snapshot: ' + model)
        print('Readiness checks do not execute model inference. Run the documented public 1UBQ smoke test.')


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prefix', type=Path, default=REPO / '.local/install')
    p.add_argument('--conda', default='conda')
    p.add_argument('--models', default='all', help='Comma-separated lowercase model IDs')
    p.add_argument('--stage', choices=['all', 'sources', 'envs', 'weights', 'config', 'check'], default='all')
    p.add_argument('--plan', action='store_true')
    for name in ('msms-bin', 'apbs-bin', 'multivalue-bin', 'netsolp-models', 'gatsol-checkpoint', 'pro4s-checkpoint'):
        p.add_argument('--' + name, type=Path)
    args = p.parse_args(argv)
    args.models = list(NAMES) if args.models == 'all' else list(dict.fromkeys(args.models.split(',')))
    if not args.models or any(m not in NAMES for m in args.models):
        p.error('Unknown model; choose ' + ','.join(NAMES))
    return args


def main(argv=None):
    args = parse_args(argv)
    installer = Installer(args)
    stages = ['sources', 'envs', 'weights', 'config', 'check'] if args.stage == 'all' else [args.stage]
    if args.plan:
        print(json.dumps({'prefix': str(installer.root), 'models': args.models, 'stages': stages}, indent=2))
        return 0
    installer.root.mkdir(parents=True, exist_ok=True)
    marker = installer.root / '.screen-installer'
    if not marker.exists():
        # Allow only shell bootstrap files; do not adopt an unrelated install directory.
        unexpected = set(p.name for p in installer.root.iterdir()) - {'miniforge', 'downloads', 'install.log'}
        if unexpected:
            raise ValueError('Use an empty dedicated --prefix; found ' + ', '.join(sorted(unexpected)))
        marker.write_text('protein-screen installer v1\n')
    with (installer.root / '.install.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = {'models': args.models, 'stages': {}, 'started': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
        for stage in stages:
            before = len(installer.errors)
            try:
                getattr(installer, stage)()
            except Exception as error:
                installer.errors.append(stage + ': ' + str(error))
                print(installer.errors[-1], file=sys.stderr)
            report['stages'][stage] = 'ok' if len(installer.errors) == before else 'incomplete'
            report['errors'] = installer.errors
            report['inference_verified'] = False
            (installer.root / 'install-report.json').write_text(json.dumps(report, indent=2) + '\n')
            if stage in ('sources', 'envs') and len(installer.errors) != before:
                break  # Dependent stages must not consume incomplete/modified sources or environments.
        print('Report:', installer.root / 'install-report.json')
        if installer.errors:
            print('INCOMPLETE — resolve errors and rerun the same command:', file=sys.stderr)
            for error in installer.errors:
                print(' - ' + error, file=sys.stderr)
            return 1
        print('Requested stages completed; inference acceptance remains a separate smoke test.')
        return 0


if __name__ == '__main__':
    sys.exit(main())
