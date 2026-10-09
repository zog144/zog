"""Generate synthetic, non-bootable host-install interoperability fixtures."""
import argparse
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

from .engine import SCHEMA
from .errors import ImageBuildError
from .filesystem import inventory, digest, write_json
from .host_export import export
from .metadata import identity


def generate(destination):
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ImageBuildError('fixture destination must be new')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as scratch:
        scratch = Path(scratch)
        root = scratch/'root'; (root/'usr/share/host-install-fixture').mkdir(parents=True)
        (root/'usr/share/host-install-fixture/README').write_text('Synthetic interoperability fixture. NOT BOOTABLE. No executable host services.\n')
        (root/'usr/bin').mkdir(); (root/'bin').symlink_to('usr/bin')
        (root/'tmp').mkdir(); (root/'tmp').chmod(0o1777)
        for path in root.rglob('*'):
            if not path.is_symlink(): path.chmod(0o755 if path.is_dir() else 0o644)
        (root/'tmp').chmod(0o1777)
        inputs = {'kind':'host-bootstrap', 'architecture':'x86_64', 'fixture':'host-install-v1'}
        generation = scratch/identity(inputs); generation.mkdir(); root.rename(generation/'root')
        manifest = {'schema':SCHEMA, 'generation':generation.name, 'kind':'host-bootstrap',
                    'inputs':inputs, 'outputs':inventory(generation/'root')}
        write_json(generation/'manifest.json', manifest)
        bundle = scratch/'fixtures'; bundle.mkdir()
        valid = export(generation, bundle/'valid', {'packages':[], 'acceptance':[]})
        cases = [{'directory':'valid', 'expected_id':valid['artifact_id'], 'verify':'accept',
                  'installable':False, 'reason':'valid synthetic artifact; no boot acceptance'}]
        shutil.copytree(bundle/'valid', bundle/'corrupt-payload')
        p = bundle/'corrupt-payload/rootfs.tar'
        with p.open('r+b') as stream: stream.write(b'CORRUPTED')
        cases.append({'directory':'corrupt-payload', 'expected_id':valid['artifact_id'],
                      'verify':'reject', 'reason':'payload hash mismatch'})
        for name in ['unsafe-path', 'false-readiness']:
            d = bundle/name; shutil.copytree(bundle/'valid', d)
            m = json.loads((d/'manifest.json').read_text())
            if name == 'unsafe-path':
                with tarfile.open(d/'rootfs.tar', 'w', format=tarfile.USTAR_FORMAT) as t:
                    t.addfile(tarfile.TarInfo('../escape'))
                m['rootfs'].update(sha256=digest(d/'rootfs.tar'), bytes=(d/'rootfs.tar').stat().st_size)
            else: m['readiness']['installable'] = True
            m.pop('artifact_id'); m['artifact_id'] = identity(m); write_json(d/'manifest.json', m)
            cases.append({'directory':name, 'expected_id':m['artifact_id'], 'verify':'reject',
                          'reason':'unsafe member path' if name == 'unsafe-path' else 'unsupported readiness claim'})
        report = {'schema':1, 'fixture':'host-install-v1', 'synthetic':True,
                  'trust':'Expected IDs must come from the reviewed repository commit, not an untrusted bundle.',
                  'cases':cases}
        write_json(bundle/'expectations.json', report)
        bundle.rename(destination)
        return report


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('destination')
    args = p.parse_args()
    print(json.dumps(generate(args.destination), indent=2))


if __name__ == '__main__': main()
