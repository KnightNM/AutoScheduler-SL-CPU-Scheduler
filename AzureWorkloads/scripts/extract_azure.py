"""Preflight every tar member, then copy only regular files (never links)."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile

DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def extract_archive(archive, destination):
    archive, destination = Path(archive), Path(destination).resolve()
    files = []
    with tarfile.open(archive, 'r:xz') as tar:
        members = tar.getmembers()
        seen = set()
        for member in members:
            name = PurePosixPath(member.name)
            target = (destination / member.name).resolve()
            if (name.is_absolute() or '..' in name.parts or '\\' in member.name
                    or not target.is_relative_to(destination)
                    or not (member.isfile() or member.isdir()) or target in seen):
                raise ValueError(f'Unsafe or duplicate archive member: {member.name}')
            seen.add(target)
        destination.mkdir(parents=True, exist_ok=True)
        for member in members:
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # Refuse overwriting existing data; identical extracted files can be reused.
            if target.exists():
                with tar.extractfile(member) as source:
                    checksum = hashlib.sha256()
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        checksum.update(block)
                    digest = checksum.hexdigest()
                if digest is None or sha256(target) != digest:
                    raise ValueError(f'Existing extracted file differs: {target}')
            else:
                with tar.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
            files.append({'path': member.name, 'bytes': member.size, 'sha256': sha256(target)})
            print(f'Extracted {member.name} ({member.size:,} bytes)', flush=True)
    return {'archive': archive.name, 'archive_sha256': sha256(archive), 'files': files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    archives = list((args.root / 'raw').glob('*.tar.xz'))
    if args.archive is None and len(archives) != 1:
        parser.error('Provide --archive when raw/ does not contain exactly one .tar.xz')
    result = extract_archive(args.archive or archives[0], args.root / 'extracted')
    (args.root / 'reports').mkdir(parents=True, exist_ok=True)
    (args.root / 'reports/extraction_manifest.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
