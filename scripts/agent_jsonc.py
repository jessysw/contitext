"""Small JSON-with-comments parser used to preserve client settings."""
import json
import re

class InstallError(ValueError):
    pass

class Token:
    def __init__(self, kind, value, start, end):
        self.kind, self.value, self.start, self.end = kind, value, start, end


class Node:
    def __init__(self, kind, start, end, value=None, members=None):
        self.kind, self.start, self.end = kind, start, end
        self.value, self.members = value, members or []


def jsonc_tokens(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i + 2)
            i = n if end < 0 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise InstallError("unterminated JSONC comment")
            i = end + 2
        elif c in "{}[]:,":
            tokens.append(Token(c, c, i, i + 1)); i += 1
        elif c == '"':
            start = i; i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1; break
                else:
                    i += 1
            else:
                raise InstallError("unterminated JSONC string")
            raw = text[start:i]
            try:
                value = json.loads(raw)
            except ValueError as exc:
                raise InstallError("invalid JSONC string: %s" % exc)
            tokens.append(Token("string", value, start, i))
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in "{}[]:," and not text.startswith("//", i) and not text.startswith("/*", i):
                i += 1
            raw = text[start:i]
            if not raw:
                raise InstallError("unsupported JSONC syntax at byte %d" % i)
            tokens.append(Token("literal", raw, start, i))
    return tokens


def parse_jsonc(text):
    tokens = jsonc_tokens(text)

    def value_at(index):
        if index >= len(tokens):
            raise InstallError("unexpected end of JSONC")
        token = tokens[index]
        if token.kind == "{":
            members = []
            index += 1
            if index < len(tokens) and tokens[index].kind == "}":
                return Node("object", token.start, tokens[index].end, members=members), index + 1
            while True:
                if index >= len(tokens) or tokens[index].kind != "string":
                    raise InstallError("JSONC object keys must be quoted strings")
                key = tokens[index].value; key_start = tokens[index].start; index += 1
                if index >= len(tokens) or tokens[index].kind != ":":
                    raise InstallError("missing colon in JSONC object")
                index += 1
                child, index = value_at(index)
                members.append((key, child, key_start))
                if index >= len(tokens):
                    raise InstallError("unterminated JSONC object")
                if tokens[index].kind == "}":
                    return Node("object", token.start, tokens[index].end, members=members), index + 1
                if tokens[index].kind != ",":
                    raise InstallError("missing comma in JSONC object")
                index += 1
                if index < len(tokens) and tokens[index].kind == "}":
                    return Node("object", token.start, tokens[index].end, members=members), index + 1
        if token.kind == "[":
            index += 1
            children = []
            if index < len(tokens) and tokens[index].kind == "]":
                return Node("array", token.start, tokens[index].end, value=children), index + 1
            while True:
                child, index = value_at(index)
                children.append(child)
                if index >= len(tokens):
                    raise InstallError("unterminated JSONC array")
                if tokens[index].kind == "]":
                    return Node("array", token.start, tokens[index].end, value=children), index + 1
                if tokens[index].kind != ",":
                    raise InstallError("missing comma in JSONC array")
                index += 1
                if index < len(tokens) and tokens[index].kind == "]":
                    return Node("array", token.start, tokens[index].end, value=children), index + 1
        if token.kind in ("string", "literal"):
            return Node("scalar", token.start, token.end, value=json.loads(text[token.start:token.end])), index + 1
        raise InstallError("invalid JSONC value")

    root, final = value_at(0)
    if final != len(tokens) or root.kind != "object":
        raise InstallError("Settings must contain one top-level JSONC object")
    return root, tokens


def member(node, name):
    found = [(child, start) for key, child, start in node.members if key == name]
    if len(found) > 1:
        raise InstallError("ambiguous duplicate JSONC key: %s" % name)
    return found[0][0] if found else None


def has_trailing_comma(text, node):
    tokens = jsonc_tokens(text[node.start:node.end])
    return len(tokens) >= 2 and tokens[-2].kind == ","


def indent_at(text, position):
    line_start = text.rfind("\n", 0, position) + 1
    match = re.match(r"[ \t]*", text[line_start:position])
    return match.group(0) if match else ""


def insert_object_member(text, node, rendered):
    close = node.end - 1
    base = indent_at(text, node.start)
    child_indent = base + "  "
    existing = bool(node.members)
    prefix = "" if not existing or has_trailing_comma(text, node) else ","
    insertion = prefix + "\n" + "\n".join(child_indent + line if line else line for line in rendered.splitlines()) + "\n" + base
    return text[:close] + insertion + text[close:]
