"""Machine-readable CLI output that also works in legacy Windows consoles."""
from __future__ import annotations

import json
import sys


def configure_utf8(*streams):
    """Prefer UTF-8 without requiring real, reconfigurable console streams."""
    for stream in streams:
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is not None:
            try:
                reconfigure(encoding='utf-8')
            except (AttributeError, OSError, ValueError):
                # Embedded callers may supply a fixed-encoding or closed wrapper.
                # emit_json still has a lossless ASCII JSON fallback below.
                pass


def emit_json(value, *, stream=None, indent=2):
    stream = sys.stdout if stream is None else stream
    configure_utf8(stream)
    payload = json.dumps(value, ensure_ascii=False, indent=indent)
    try:
        stream.write(payload + '\n')
    except UnicodeEncodeError:
        # JSON escapes retain the exact Unicode value; they are valid UTF-8 too.
        stream.write(json.dumps(value, ensure_ascii=True, indent=indent) + '\n')
