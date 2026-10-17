"""Conservative lexical scope locators; never a compiler membership claim."""
from .swiftui import tokenize


def import_token_lines(tokens):
    """Locate dependency directives, including attributed imports, without string scans."""
    return {token.line for token in tokens if token.kind != 'string' and token.value == 'import'}


def preview_lines(text):
    tokens = tokenize(text)
    result = set()
    for i, token in enumerate(tokens):
        if token.kind == 'string':
            continue
        macro = token.value == '#' and i + 1 < len(tokens) and tokens[i + 1].value == 'Preview'
        header = []
        if token.value == 'struct':
            for item in tokens[i + 1:]:
                if item.value == '{':
                    break
                header.append(item.value)
        provider = ':' in header and 'PreviewProvider' in header
        if not (macro or provider):
            continue
        start = next((j for j in range(i + 1, len(tokens)) if tokens[j].kind != 'string' and tokens[j].value == '{'), None)
        if start is None:
            continue
        depth = 0
        for j in range(start, len(tokens)):
            if tokens[j].kind == 'string':
                continue
            depth += tokens[j].value == '{'
            depth -= tokens[j].value == '}'
            if depth == 0:
                result.update(range(token.line, tokens[j].line + 1))
                break
    return result
