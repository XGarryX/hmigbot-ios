"""Import pinned MIT skill resources as data; never execute downloaded code."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PACKS = [
    ('swiftui', 'AvdLee/SwiftUI-Agent-Skill', '204dba7c67256a8b707ee3fbc5759a824191974f', ['skills/swiftui-expert-skill/']),
    ('concurrency', 'AvdLee/Swift-Concurrency-Agent-Skill', 'd5770817d2622e1585b1f7eaebc791a9cb0959c8', ['skills/swift-concurrency/']),
    ('uikit', 'CharlesWiltgen/Axiom', 'd35eaca69e423d5157bb39c2a1b5f76ff9802f86',
     ['axiom-codex/skills/axiom-uikit/', 'axiom-codex/skills/axiom-performance/skills/memory-debugging.md',
      'axiom-codex/skills/axiom-performance/skills/objc-block-retain-cycles.md']),
]


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'HMigBot-iOS-vendor'})
    return urllib.request.urlopen(request, timeout=45).read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'vendor/ios-expertise')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Use a new directory; reviewed pinned snapshots are immutable')
    manifest = {'schema_version': 1, 'imported_on': '2026-10-12', 'packs': []}
    for ident, repo, commit, prefixes in PACKS:
        tree = json.loads(get(f'https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1'))
        if tree.get('truncated'):
            raise SystemExit('Truncated GitHub tree')
        paths = [v['path'] for v in tree['tree'] if v['type'] == 'blob' and v.get('mode') != '120000'
                 and (v['path'] == 'LICENSE' or any(v['path'].startswith(p) for p in prefixes))]
        if 'LICENSE' not in paths:
            raise SystemExit('MIT license missing: ' + repo)
        def download(path):
            data = get(f'https://raw.githubusercontent.com/{repo}/{commit}/{path}')
            dest = args.output / ident / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return {'path': f'{ident}/{path}', 'upstream_path': path, 'sha256': hashlib.sha256(data).hexdigest()}
        with ThreadPoolExecutor(max_workers=6) as pool:
            files = list(pool.map(download, paths))
        license_text = (args.output / ident / 'LICENSE').read_text(encoding='utf-8')
        if 'MIT License' not in license_text or 'Permission is hereby granted' not in license_text:
            raise SystemExit('Review unexpected license: ' + repo)
        manifest['packs'].append({'id': ident, 'repository': 'https://github.com/' + repo,
                                  'commit': commit, 'license': 'MIT', 'files': sorted(files, key=lambda f: f['path'])})
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'packs': len(manifest['packs']), 'files': sum(len(p['files']) for p in manifest['packs'])}))


if __name__ == '__main__':
    main()
