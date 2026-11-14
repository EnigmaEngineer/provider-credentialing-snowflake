"""Read the configuration files well enough to ask what is not in them.

Nothing available here can grade an absence. terraform validate reads a value
and asks whether the provider accepts it, and almost every argument that
decides whether a Snowflake object does anything is optional, so a file
missing all of them validates. That is the gap this module exists to close,
and it closes it by returning the argument names a block sets so a check can
assert the ones that have to be there.

It is a reader for the subset of the language this repository writes, not a
parser for the language. It is graded against fixtures with the defect marked
in them rather than against the live files, because a check that reads code
cannot test itself.
"""

import re
from dataclasses import dataclass, field

HEREDOC = re.compile(r"<<-?([A-Za-z_][A-Za-z0-9_]*)\s*$")
ARG = re.compile(r"^([a-z_][a-z0-9_]*)\s*=")
NESTED = re.compile(r"^([a-z_][a-z0-9_]*)\s*\{\s*$")
HEADER = re.compile(r'^(resource|provider|variable|terraform|output|data)\b(.*)\{\s*$')
LABEL = re.compile(r'"([^"]*)"')


@dataclass
class Block:
    kind: str
    labels: tuple
    args: set = field(default_factory=set)
    nested: set = field(default_factory=set)
    # Argument names set inside nested blocks, pooled. A rule about an
    # argument that must never appear has to reach these, because a nested
    # block is exactly where a credential would be written.
    nested_args: set = field(default_factory=set)

    @property
    def label(self):
        return ".".join(self.labels)


def _strip_comment(line):
    """Remove a trailing comment, leaving anything inside a quoted string alone."""
    out = []
    in_string = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and in_string:
            out.append(line[i : i + 2])
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
        elif not in_string and ch == "#":
            break
        elif not in_string and ch == "/" and line[i : i + 2] == "//":
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def strip_comments(text):
    """The file with every comment removed and nothing else changed.

    A check whose subject is what the configuration does must not be
    satisfiable, or breakable, by a sentence sitting beside the configuration.
    The first version of the rule about private keys failed on the comment
    explaining that the deploy carries no password, and the two tempting fixes
    are deleting the explanation or weakening the rule.
    """
    return "\n".join(_strip_comment(line) for line in text.splitlines())


def blocks(text):
    """Every top level block, with the argument and nested block names it sets."""
    found = []
    current = None
    depth = 0
    heredoc_tag = None

    for raw in text.splitlines():
        if heredoc_tag is not None:
            if raw.strip() == heredoc_tag:
                heredoc_tag = None
            continue

        line = _strip_comment(raw).strip()
        if not line:
            continue

        m = HEREDOC.search(line)
        if m:
            heredoc_tag = m.group(1)
            am = ARG.match(line)
            if am and current is not None:
                # A heredoc is where a body goes and a body is somewhere a
                # credential can be written, so the name is recorded at
                # whatever depth it was set at. It used to be recorded only at
                # the top level, which meant an argument opened as a heredoc
                # inside a nested block reached neither set and no rule about
                # arguments that must not appear could see it.
                if depth == 1:
                    current.args.add(am.group(1))
                else:
                    current.nested_args.add(am.group(1))
            continue

        if depth == 0:
            hm = HEADER.match(line)
            if hm:
                current = Block(kind=hm.group(1), labels=tuple(LABEL.findall(hm.group(2))))
                found.append(current)
                depth = 1
            continue

        if depth == 1:
            nm = NESTED.match(line)
            if nm:
                current.nested.add(nm.group(1))
                depth = 2
                continue
            am = ARG.match(line)
            if am:
                current.args.add(am.group(1))
            if line in ("}", "},"):
                depth = 0
                current = None
            continue

        # Deeper than one level in.
        am = ARG.match(line)
        if am and current is not None:
            current.nested_args.add(am.group(1))
        nm = NESTED.match(line)
        if nm and current is not None:
            current.nested.add(nm.group(1))
        depth += line.count("{") - line.count("}")
        if depth < 1:
            depth = 0
            current = None


    return found


def resources(text, kind=None):
    out = [b for b in blocks(text) if b.kind == "resource"]
    if kind is not None:
        out = [b for b in out if b.labels and b.labels[0] == kind]
    return out


def read_dir(path, suffix=".tf"):
    """Concatenate a directory of configuration files into one block list."""
    import os

    found = []
    for name in sorted(os.listdir(path)):
        if name.endswith(suffix):
            with open(os.path.join(path, name), encoding="utf-8") as fh:
                for b in blocks(fh.read()):
                    found.append((name, b))
    return found
