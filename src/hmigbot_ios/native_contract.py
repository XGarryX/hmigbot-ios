"""Authoring and source gates share these source-evidence contracts."""
from .core import MigrationError, safe_child


def validate_disposition(item, known):
    from .artifact_contract import validate_json
    try:
        validate_json(item, 'source_disposition_entry')
    except MigrationError as exc:
        raise MigrationError('Invalid source disposition: ' + str(exc)) from exc
    if item['path'] not in known:
        raise MigrationError('Source disposition path is outside the current source index')
    return item


def source_truth(source, anchors, path, line):
    """Render only a real line in this feature's declared source files."""
    if not isinstance(path, str):
        raise MigrationError('Truth path must be a source-relative string')
    file = safe_child(source, path)
    if (path not in anchors or type(line) is not int
            or not file.is_file() or not 1 <= line <= len(file.read_text(encoding='utf-8-sig').splitlines())):
        raise MigrationError('Truth location is outside the feature anchors or line range')
    return f'真:src:{path}:{line}'
