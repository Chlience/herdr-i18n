"""Just enough of a JavaScript lexer to find the text in Herdr's mods.

It finds string literals, template literals (with the strings and templates
nested in their ${...}), regular expression literals and comments, so that a
quote inside a regex or a comment never pairs with a real string.
"""
import re

# After these, a "/" starts a regular expression rather than a division.
_REGEX_AFTER_PUNCT = set('([{,;:=!&|?+-*%<>~^}')
_REGEX_AFTER_WORD = {'return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete',
                     'void', 'throw', 'case', 'do', 'else', 'yield', 'await'}
_WORD = re.compile(r'[A-Za-z_$\u0080-\uffff][\w$\u0080-\uffff]*')
_NUMBER = re.compile(r'\.?\d[\w.]*')
_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f', 'v': '\v'}


class LexError(ValueError):
    pass


class Token:
    """kind is string, template, regex or comment; start/end index the source."""
    __slots__ = ('kind', 'start', 'end', 'children', 'holes')

    def __init__(self, kind, start, end, children=(), holes=()):
        self.kind, self.start, self.end = kind, start, end
        self.children = list(children)  # tokens inside a template's ${...}
        self.holes = list(holes)  # (start, end) of each ${...}, braces included

    def __repr__(self):
        return f'Token({self.kind}, {self.start}, {self.end})'


def tokenize(src):
    """The top-level tokens of src; templates carry their nested ones."""
    end, tokens = _code(src, 0, nested=False)
    return tokens


def _line(src, i):
    return src.count('\n', 0, i) + 1


def _code(src, i, nested):
    n = len(src)
    tokens = []
    depth = 0
    prev = None  # the last significant token: a punctuation char, a word, or a kind
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
        elif src.startswith('//', i):
            j = src.find('\n', i)
            j = n if j < 0 else j
            tokens.append(Token('comment', i, j))
            i = j
        elif src.startswith('/*', i):
            j = src.find('*/', i + 2)
            if j < 0:
                raise LexError(f'unterminated comment at line {_line(src, i)}')
            tokens.append(Token('comment', i, j + 2))
            i = j + 2
        elif c in '"\'':
            j = _string_end(src, i)
            tokens.append(Token('string', i, j))
            i, prev = j, 'string'
        elif c == '`':
            token = _template(src, i)
            tokens.append(token)
            i, prev = token.end, 'template'
        elif c == '/' and (prev is None or prev in _REGEX_AFTER_PUNCT or prev in _REGEX_AFTER_WORD):
            j = _regex_end(src, i)
            tokens.append(Token('regex', i, j))
            i, prev = j, 'regex'
        elif _WORD.match(src, i):
            m = _WORD.match(src, i)
            i, prev = m.end(), m.group()
        elif c.isdigit() or (c == '.' and src[i + 1:i + 2].isdigit()):
            m = _NUMBER.match(src, i)
            i, prev = m.end(), 'number'
        else:
            if c == '{':
                depth += 1
            elif c == '}':
                if depth == 0 and nested:
                    return i + 1, tokens
                depth -= 1
            i, prev = i + 1, c
    if nested:
        raise LexError('unterminated ${ in a template')
    return i, tokens


def _string_end(src, i):
    quote, j, n = src[i], i + 1, len(src)
    while j < n:
        c = src[j]
        if c == '\\':
            j += 2
        elif c == quote:
            return j + 1
        elif c == '\n':
            break
        else:
            j += 1
    raise LexError(f'unterminated string at line {_line(src, i)}')


def _regex_end(src, i):
    j, n, in_class = i + 1, len(src), False
    while j < n:
        c = src[j]
        if c == '\\':
            j += 2
            continue
        if c == '\n':
            break
        if in_class:
            in_class = c != ']'
        elif c == '[':
            in_class = True
        elif c == '/':
            j += 1
            while j < n and (src[j].isalnum() or src[j] in '_$'):
                j += 1
            return j
        j += 1
    raise LexError(f'unterminated regular expression at line {_line(src, i)}')


def _template(src, i):
    j, n = i + 1, len(src)
    children, holes = [], []
    while j < n:
        c = src[j]
        if c == '\\':
            j += 2
        elif c == '`':
            return Token('template', i, j + 1, children, holes)
        elif src.startswith('${', j):
            end, nested = _code(src, j + 2, nested=True)
            holes.append((j, end))
            children.extend(nested)
            j = end
        else:
            j += 1
    raise LexError(f'unterminated template at line {_line(src, i)}')


def string_value(literal):
    """The text a quoted JavaScript string literal stands for."""
    body, out, i = literal[1:-1], [], 0
    while i < len(body):
        c = body[i]
        if c != '\\':
            out.append(c)
            i += 1
            continue
        e = body[i + 1]
        if e == 'u' and body[i + 2] == '{':
            j = body.index('}', i)
            out.append(chr(int(body[i + 3:j], 16)))
            i = j + 1
        elif e == 'u':
            out.append(chr(int(body[i + 2:i + 6], 16)))
            i += 6
        elif e == 'x':
            out.append(chr(int(body[i + 2:i + 4], 16)))
            i += 4
        elif e == '0' and not body[i + 2:i + 3].isdigit():
            out.append('\0')
            i += 2
        elif e == '\r':
            i += 3 if body[i + 2:i + 3] == '\n' else 2
        elif e == '\n':
            i += 2
        else:
            out.append(_ESCAPES.get(e, e))
            i += 2
    # 😀 pairs arrive as two halves.
    return ''.join(out).encode('utf-16', 'surrogatepass').decode('utf-16')


def holes(template_body):
    """The code of each ${...} in a template body (the text between backticks), sorted.

    Text nested in that code (strings, template text) is left out, so it may be
    translated; the code around it, and any ${...} nested deeper, may not change.
    """
    src = '`' + template_body + '`'
    tokens = tokenize(src)
    if len(tokens) != 1 or tokens[0].kind != 'template' or tokens[0].end != len(src):
        raise LexError('not a single template')
    return _shape(src, tokens[0])


def skeleton(src):
    """src without its text: what must stay equal for a translation to change no behavior."""
    return _code_shape(src, tokenize(src), 0, len(src))


def _shape(src, template):
    return sorted(_code_shape(src, [t for t in template.children if a <= t.start < b], a + 2, b - 1)
                  for a, b in template.holes)


def _code_shape(src, tokens, start, end):
    out, i = [], start
    for t in tokens:
        out.append(re.sub(r'\s+', '', src[i:t.start]))
        if t.kind == 'string':
            out.append('""')
        elif t.kind == 'template':
            out.append('`' + ''.join('${' + h + '}' for h in _shape(src, t)) + '`')
        elif t.kind == 'regex':
            out.append(src[t.start:t.end])
        i = t.end
    out.append(re.sub(r'\s+', '', src[i:end]))
    return ''.join(out)
