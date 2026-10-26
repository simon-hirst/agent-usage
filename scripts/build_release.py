#!/usr/bin/env python3
"""Build a self-contained platform-specific distribution with PyInstaller.

Run this script natively on the target OS/CPU architecture; no cross-compiling.
User credentials are never read or packaged.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'ProviderUsageTray'
SOURCES = [
    ('desktop/managed-wsl.sh', 'desktop'),
    ('desktop/direct_usage.py', 'desktop'),
    ('desktop/extra_readers.py', 'desktop'),
    ('desktop/direct-usage.sh', 'desktop'),
    ('work-codex-usage-api/server.py', 'work-codex-usage-api'),
    ('claude-usage-api/server.py', 'claude-usage-api'),
]


def build(version: str, target: str, artifact_dir: Path) -> Path:
    system = platform.system()
    expected_os = target.split('-')[0]
    current = {'Windows': 'windows', 'Darwin': 'macos', 'Linux': 'linux'}[system]
    if expected_os != current:
        raise ValueError(f'{target} must be built on {expected_os}, not {current}')
    arch = platform.machine().lower()
    if target.endswith('-arm64') and arch not in ('arm64', 'aarch64'):
        raise ValueError(f'ARM64 build requested on {arch}')
    if target.endswith('-x64') and arch not in ('amd64', 'x86_64'):
        raise ValueError(f'x64 build requested on {arch}')
    release_name = f'provider-usage-tray-{version}-{target}'
    workdir = ROOT / '.release-build'
    dist = workdir / 'dist'
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir()
    cmd = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--onedir', '--windowed', '--name', NAME,
        '--distpath', str(dist), '--workpath', str(workdir / 'build'),
        '--specpath', str(workdir), '--paths', str(ROOT),
    ]
    for src, dest in SOURCES:
        cmd += ['--add-data', str(ROOT / src) + os.pathsep + dest]
    cmd += [str(ROOT / 'desktop' / 'bundled_entry.py')]
    subprocess.run(cmd, cwd=ROOT, check=True)
    if system == 'Darwin':
        exe = dist / f'{NAME}.app' / 'Contents' / 'MacOS' / NAME
        bundle = dist / f'{NAME}.app'
    else:
        bundle = dist / NAME
        exe = bundle / (NAME + '.exe' if system == 'Windows' else NAME)
    if not exe.exists():
        raise RuntimeError(f'Expected executable not generated: {exe}')
    # Binary smoke: both server entrypoints + Qt UI, with NO authenticated CLIs needed.
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    subprocess.run([str(exe), '--verify-bundle'], cwd=ROOT, env=env, check=True, timeout=75)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / 'direct-smoke.json'
        subprocess.run([str(exe), '--direct-usage', 'verify-no-login', '--output', str(output)],
                       cwd=ROOT, env=env, stdout=subprocess.DEVNULL, timeout=20, check=True)
        if not output.is_file() or '"ok":false' not in output.read_text(encoding='utf-8'):
            raise RuntimeError('Bundled direct-reader result file is broken')
    for service in ('codex', 'claude'):
        subprocess.run([str(exe), '--backend-server', service, '--help'],
                       cwd=ROOT, env=env, check=True, timeout=75,
                       stdout=subprocess.DEVNULL)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if system == 'Darwin':
        artifact = artifact_dir / f'{release_name}.app.zip'
        subprocess.run(['ditto', '-c', '-k', '--keepParent', str(bundle), str(artifact)], check=True)
    elif system == 'Windows':
        artifact = artifact_dir / f'{release_name}.zip'
        with zipfile.ZipFile(artifact, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as out:
            for file in bundle.rglob('*'):
                if file.is_file():
                    out.write(file, file.relative_to(dist))
    else:
        artifact = artifact_dir / f'{release_name}.tar.gz'
        with tarfile.open(artifact, 'w:gz') as out:
            out.add(bundle, arcname=NAME)
    print(f'BUILT {artifact} ({artifact.stat().st_size:,} bytes)', flush=True)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True, help='Git tag such as v3.1.0')
    parser.add_argument('--target', required=True, choices=[
        'windows-x64', 'windows-arm64', 'macos-x64', 'macos-arm64', 'linux-x64', 'linux-arm64'])
    parser.add_argument('--output', type=Path, default=ROOT / 'release-assets')
    args = parser.parse_args()
    if not args.version.startswith('v') or any(c not in '0123456789.v-' for c in args.version):
        parser.error('Version must be a simple v-prefixed tag (for example v3.1.0)')
    build(args.version, args.target, args.output.resolve())


if __name__ == '__main__':
    main()
