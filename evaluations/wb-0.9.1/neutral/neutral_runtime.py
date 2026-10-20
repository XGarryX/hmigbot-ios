"""Explicit, recorded local runtime selection for neutral host evaluations."""
import json
import os
from pathlib import Path
import shutil
import subprocess


def add_runtime_options(parser):
    parser.add_argument('--node', type=Path,
        default=os.environ.get('HMIGBOT_NEUTRAL_NODE') or shutil.which('node')
        or 'D:/Program Files/nodejs/node.exe',
        help='Existing Node executable (or HMIGBOT_NEUTRAL_NODE / PATH)')
    parser.add_argument('--typescript', type=Path,
        default=os.environ.get('HMIGBOT_NEUTRAL_TYPESCRIPT')
        or 'D:/Program Files/DevEco Studio/tools/hvigor/hvigor/node_modules/typescript/lib/typescript.js',
        help='Existing typescript.js module (or HMIGBOT_NEUTRAL_TYPESCRIPT)')


def resolve_runtime(args, parser):
    from hmigbot_ios.core import digest
    node, ts = args.node.resolve(), args.typescript.resolve()
    for label, path in (('--node', node), ('--typescript', ts)):
        if not path.is_file():
            parser.error('%s must point to an existing runtime file; supply that option explicitly' % label)
    try:
        probe = subprocess.run([str(node), '-e',
            'console.log(JSON.stringify({node:process.version,typescript:require(process.argv[1]).version}))',
            str(ts)], capture_output=True, text=True, encoding='utf-8', timeout=15, check=True)
        versions = json.loads(probe.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.error('Cannot load selected Node/TypeScript runtime: %s' % exc)
    metadata = {'node': str(node), 'node_sha256': digest(node.read_bytes()),
                'typescript': str(ts), 'typescript_sha256': digest(ts.read_bytes()),
                'versions': versions}
    return str(node), ts, metadata
