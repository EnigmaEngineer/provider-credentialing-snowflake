"""The monthly cycle as a graph, with the order derived instead of typed.

The ordering defect this exists to make unreachable is in the README and in
`ot-242`. The snapshots read the staging models, so a cycle that snapshots
before it transforms fails on a fresh warehouse with a catalog error. The
obvious fix is to write the order correctly in the DAG and move on. That fix
lasts until the next person edits the DAG.

So no stage here declares what comes before it. A stage declares the relations
it produces, every dependency between relations is read out of the project's
own SQL and its own source declarations, and the run order is a topological
sort over what that produces. Writing the wrong order is not something the
caller can do, because the caller does not write an order at all.

What the derivation refuses. Each one is a defect rather than tidiness.

- A model or a snapshot no stage produces. It would be left out of the monthly
  cycle in silence, which is the 2026-11-13 lesson about a manifest that cannot
  disagree with what it does not mention.
- A relation two stages both produce. Two overlapping selectors means one runs
  work the other already did, and on a snapshot it means two versions recorded
  for one change.
- A dependency that points backwards. That is the catalog error above, raised
  before anything runs.
- A source a model reads that no stage lands, unless it is named below with the
  reason. The named set is compared against what the derivation finds, in both
  directions, so a second unlanded source fails rather than joining the
  exception quietly.
"""

import os
import re

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJECT = os.path.join(ROOT, "transform")

# dbt's own syntax, either quote style. The project writes it one way and a
# reader that only accepts that way breaks on a reformat.
REF = re.compile(r"""ref\(\s*['"]([A-Za-z0-9_]+)['"]\s*\)""")
SOURCE = re.compile(r"""source\(\s*['"]([A-Za-z0-9_]+)['"]\s*,\s*['"]([A-Za-z0-9_]+)['"]\s*\)""")

# The one source the cycle reads and does not land, with the reason.
#
# The screening events are written by the screening itself and not replicated
# from anywhere, and nothing in this repository writes them. So the monthly
# cycle reads a table it has no task for. Naming it here keeps the gap in the
# code and in the README rather than leaving the graph to imply the cycle is
# closed. There is a check asserting this set is exactly what the derivation
# finds unlanded.
SOURCES_THE_CYCLE_DOES_NOT_LAND = ("screening",)


class CycleOrderError(Exception):
    """Raised when the declared stages cannot produce a runnable order."""


def source_key(source, table):
    return "source:%s.%s" % (source, table)


class Node:
    """A relation dbt builds, and what it reads."""

    def __init__(self, name, kind, directory, reads):
        self.name = name
        self.kind = kind
        self.directory = directory
        self.reads = tuple(sorted(set(reads)))

    def __repr__(self):
        return "Node(%r, %r)" % (self.name, self.kind)


class Project:
    def __init__(self, nodes, sources):
        self.nodes = nodes
        self.sources = tuple(sorted(sources))

    def models_in(self, directory):
        return sorted(
            name
            for name, node in self.nodes.items()
            if node.kind == "model" and node.directory == directory
        )

    def snapshots(self):
        return sorted(name for name, node in self.nodes.items() if node.kind == "snapshot")

    def source_tables(self, source):
        prefix = "source:%s." % source
        return sorted(key for key in self.sources if key.startswith(prefix))


class Stage:
    """One step of the cycle.

    `selector` is how dbt is told what to do and `produces` is the set of
    relations that resolves to. The two are kept apart because the selector is
    a string handed to another program and the set is what the ordering reasons
    about.
    """

    def __init__(
        self,
        name,
        command,
        selector,
        produces,
        consumes=(),
        needs_account=False,
        note="",
    ):
        self.name = name
        # None where the cycle waits on a system that runs on its own
        # schedule rather than running something. The pipe fires on a
        # notification and the replication connector syncs on its own clock,
        # so neither is a task this orchestrator starts.
        self.command = command
        self.selector = selector
        self.produces = frozenset(produces)
        # Relations the stage reads and does not produce. A grading stage
        # produces nothing, so without this it has no derived position and
        # would sit wherever it was written.
        self.consumes = frozenset(consumes)
        self.needs_account = needs_account
        self.note = note

    def __repr__(self):
        return "Stage(%r, produces=%d)" % (self.name, len(self.produces))


def _sql_files(directory):
    for base, _dirs, names in os.walk(directory):
        for name in sorted(names):
            if name.endswith(".sql") and not name.startswith("_"):
                yield os.path.join(base, name)


def _declared_sources(project):
    found = set()
    for base, _dirs, names in os.walk(os.path.join(project, "models")):
        for name in sorted(names):
            if not name.endswith((".yml", ".yaml")):
                continue
            with open(os.path.join(base, name), encoding="utf-8") as fh:
                body = yaml.safe_load(fh) or {}
            for source in body.get("sources") or []:
                for table in source.get("tables") or []:
                    found.add(source_key(source["name"], table["name"]))
    return found


def read_project(project=PROJECT):
    """Every model and snapshot in the project, with what each one reads.

    The name is the file stem because that is what dbt does, and the reads come
    out of the file's own `ref` and `source` calls. Nothing here is typed, so a
    model added tomorrow is in this answer without anybody editing it.
    """
    nodes = {}
    for kind, root in (("model", "models"), ("snapshot", "snapshots")):
        base = os.path.join(project, root)
        if not os.path.isdir(base):
            continue
        for path in _sql_files(base):
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
            name = os.path.splitext(os.path.basename(path))[0]
            directory = os.path.basename(os.path.dirname(path))
            if name in nodes:
                raise CycleOrderError("two files define the relation %r" % name)
            reads = list(REF.findall(body))
            reads += [source_key(one, two) for one, two in SOURCE.findall(body)]
            nodes[name] = Node(name, kind, directory, reads)
    return Project(nodes, _declared_sources(project))


def stages(project=None):
    """The cycle's stages, in declaration order and not in run order.

    Declaration order is a tiebreak and nothing else. Two stages with no
    dependency between them run in the order they appear here, and the only
    such pair is the history and the marts. The history goes first because it
    is the state the match read and recording it first costs nothing.
    """
    project = read_project() if project is None else project
    return (
        Stage(
            "land_registry_files",
            "python scripts/fetch.py --out data/raw",
            "",
            project.source_tables("registry"),
            needs_account=True,
            note="The weekly file and the exclusion list into the stage prefix, then the pipe.",
        ),
        Stage(
            "replicate_credentialing",
            None,
            "",
            project.source_tables("credentialing"),
            needs_account=True,
            note=(
                "A boundary and not a task. The connector syncs on its own clock, so what "
                "belongs here is a deferrable sensor on its last completed sync. There is no "
                "account to poll, so the cycle marks the boundary and the README says so."
            ),
        ),
        Stage(
            "transform_staging",
            "dbt run --select staging",
            "staging",
            project.models_in("staging"),
            note="The deletion marker and the sentinel identifier are handled here and nowhere after.",
        ),
        Stage(
            "record_attribute_history",
            "dbt snapshot",
            "",
            project.snapshots(),
            note="Reads the staging models, which is the whole reason this stage cannot float.",
        ),
        Stage(
            "transform_intermediate",
            "dbt run --select intermediate",
            "intermediate",
            project.models_in("intermediate"),
            note="The match, the screening answer and the currency rule.",
        ),
        Stage(
            "grade_the_cycle",
            "dbt test",
            "",
            (),
            consumes=sorted(project.nodes),
            note="The assertions, including the one that fails when a live provider is outside the window.",
        ),
    )


def owner_of(declared):
    """Which stage produces each relation, refusing an overlap."""
    owner = {}
    for stage in declared:
        for relation in sorted(stage.produces):
            if relation in owner:
                raise CycleOrderError(
                    "%r is produced by both %r and %r" % (relation, owner[relation], stage.name)
                )
            owner[relation] = stage.name
    return owner


def unlanded_sources(project=None, declared=None):
    """Sources a model reads that no stage lands."""
    project = read_project() if project is None else project
    declared = stages(project) if declared is None else tuple(declared)
    owner = owner_of(declared)
    wanted = set()
    for node in project.nodes.values():
        wanted.update(read for read in node.reads if read.startswith("source:"))
    return tuple(sorted(key for key in wanted if key not in owner))


def _needs(project, declared, owner):
    """Stage to stages, before any reduction.

    A stage needs another when a relation it produces reads a relation that
    one produces, or when it consumes one directly. A read of something
    nothing produces carries no ordering, and the named sources above are the
    only such reads.
    """
    needs = {stage.name: set() for stage in declared}
    for name, node in sorted(project.nodes.items()):
        for read in node.reads:
            if read in owner and owner[name] != owner[read]:
                needs[owner[name]].add(owner[read])
    for stage in declared:
        for relation in sorted(stage.consumes):
            if relation in owner and owner[relation] != stage.name:
                needs[stage.name].add(owner[relation])
    return needs


def _reachable(needs, start):
    seen, stack = set(), list(needs[start])
    while stack:
        here = stack.pop()
        if here in seen:
            continue
        seen.add(here)
        stack.extend(needs[here])
    return seen


def dependencies(project=None, declared=None):
    """The edges to wire, with the implied ones removed.

    An edge A to C that two other edges already imply is an edge a reader has
    to check and the scheduler gains nothing from. The reduction runs over the
    full relation, so removing one never changes what the order permits.
    """
    project = read_project() if project is None else project
    declared = stages(project) if declared is None else tuple(declared)
    needs = _needs(project, declared, owner_of(declared))
    reduced = {}
    for name in needs:
        indirect = set()
        for parent in needs[name]:
            indirect.update(_reachable(needs, parent))
        reduced[name] = frozenset(needs[name] - indirect)
    return reduced


def plan(project=None, declared=None):
    """The stages in an order the warehouse will accept, or an exception.

    There is no argument for the order. Pass a different set of stages and the
    order changes with it, which is the only way to change it.
    """
    project = read_project() if project is None else project
    declared = stages(project) if declared is None else tuple(declared)
    owner = owner_of(declared)
    by_name = {stage.name: stage for stage in declared}

    missing = sorted(name for name in project.nodes if name not in owner)
    if missing:
        raise CycleOrderError(
            "the project has relations no stage produces, so the cycle would skip them: %r"
            % missing
        )

    stray = sorted(
        key
        for key in unlanded_sources(project, declared)
        if key.split(":", 1)[1].split(".", 1)[0] not in SOURCES_THE_CYCLE_DOES_NOT_LAND
    )
    if stray:
        raise CycleOrderError(
            "the cycle reads sources it does not land and does not name: %r" % stray
        )

    needs = _needs(project, declared, owner)

    order, placed = [], set()
    remaining = [stage.name for stage in declared]
    while remaining:
        ready = [name for name in remaining if needs[name] <= placed]
        if not ready:
            raise CycleOrderError(
                "the stages cannot be ordered, so something reads its own output: %r" % remaining
            )
        # Declaration order among the ready ones. Sorting by name here would
        # make the run order depend on a stage's spelling.
        take = ready[0]
        order.append(by_name[take])
        placed.add(take)
        remaining.remove(take)
    return tuple(order)


def ordering_reasons(project=None, declared=None):
    """Why each stage sits where it does, as one row per dependency.

    Four fields. The stage that waits and the stage it waits for, then the
    relation whose read caused it and the relation that was read. A grading
    stage produces nothing, so its rows come from what it consumes, and that
    half was missing the first time this ran. The check comparing these rows
    against the parsed edges is what said so.
    """
    project = read_project() if project is None else project
    declared = stages(project) if declared is None else tuple(declared)
    owner = owner_of(declared)
    reasons = set()
    for name, node in sorted(project.nodes.items()):
        for read in node.reads:
            if read in owner and owner[name] != owner[read]:
                reasons.add((owner[name], owner[read], name, read))
    for stage in declared:
        for relation in sorted(stage.consumes):
            if relation in owner and owner[relation] != stage.name:
                reasons.add((stage.name, owner[relation], stage.name, relation))
    return tuple(sorted(reasons))
