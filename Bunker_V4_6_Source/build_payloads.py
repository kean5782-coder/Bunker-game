"""Repack edited game sources; keep the tested vendor archive by default.

Python standard library only for the default command. Use --rebuild-vendor
only inside the original, version-matched dependency environment.
"""
from pathlib import Path
import argparse
import importlib.metadata as meta
import json
import zipfile

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--rebuild-vendor', action='store_true')
args = parser.parse_args()
with zipfile.ZipFile(ROOT/'launcher/payload.zip', 'w', zipfile.ZIP_DEFLATED, 6) as z:
    for p in sorted((ROOT/'app').rglob('*')):
        rel = p.relative_to(ROOT/'app')
        if rel.parts[0] not in {'server','static','desktop_server.py'}:
            continue
        if (p.is_file() and '__pycache__' not in p.parts
                and not p.name.startswith('test_')
                and p.suffix.lower() not in {'.pyc','.log','.ttf','.otf','.woff','.woff2'}):
            z.write(p, rel)
if args.rebuild_vendor:
    expected = json.loads((ROOT/'VENDOR_VERSIONS.json').read_text())
    for name, version in expected.items():
        actual = meta.version(name)
        if actual != version:
            raise SystemExit(f'{name}: expected {version}, found {actual}; refusing untested vendor update')
    with zipfile.ZipFile(ROOT/'launcher/vendor.zip','w',zipfile.ZIP_DEFLATED,6) as z:
        added = set()
        for name in expected:
            d = meta.distribution(name)
            for f in d.files or []:
                n = str(f)
                if (n.startswith('../') or '__pycache__' in n
                        or any(t in Path(n).parts for t in ('tests','test'))
                        or Path(n).suffix.lower() in {'.pyc','.so','.pyd','.exe','.woff','.woff2','.ttf','.otf'}):
                    continue
                p = Path(d.locate_file(f))
                if not p.is_file() or n in added:
                    continue
                z.write(p,n)
                added.add(n)
        z.writestr('BUNKER_VENDOR_MANIFEST.json',json.dumps(expected,indent=2))
print('App payload:', (ROOT/'launcher/payload.zip').stat().st_size)
print('Vendor payload:', (ROOT/'launcher/vendor.zip').stat().st_size)
