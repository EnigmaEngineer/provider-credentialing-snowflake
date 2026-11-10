"""What a logical replication slot actually carries, per replica identity.

    python3 scripts/measure_replication.py --dsn 'host=/tmp user=cred dbname=postgres'

The connector configuration names a replication method. The method's
description says it replicates new, changed and deleted rows. What reaches the
destination for a delete is decided somewhere else, by a property of the source
table that no connector configuration mentions. This script measures what that
property does, so the choice made in credentialing/schema.sql rests on an
answer rather than on a vendor sentence.

Five tables, one per replica identity setting, plus a table with no primary
key. Each gets one insert, one update and one delete. Then the slot is drained
and every message is read by its type byte.

The pgoutput message types this reads, from the logical replication protocol:
the first byte is the message kind, and for an insert, update or delete the
next four bytes are the relation and the byte after those is the tuple tag. N
is a new tuple, K is the key columns of the old row and O is the whole old row.
So DO is a delete carrying everything and DK is a delete carrying the key.

Needs a server with wal_level set to logical. Writes measurements/replication.json.
"""

import argparse
import json
import os
import subprocess
import sys

OUT = os.path.join("measurements", "replication.json")

SCHEMA = "replication_probe"
SLOT = "replication_probe_slot"
PUBLICATION = "replication_probe_pub"

# name, the DDL that makes it, the ALTER that sets its identity
ARMS = (
    ("pk_default", "a int PRIMARY KEY, b text", None),
    ("pk_full", "a int PRIMARY KEY, b text", "REPLICA IDENTITY FULL"),
    ("pk_index", "a int PRIMARY KEY, b text NOT NULL", "REPLICA IDENTITY USING INDEX pk_index_uq"),
    ("no_pk", "a int, b text", None),
    ("identity_nothing", "a int PRIMARY KEY, b text", "REPLICA IDENTITY NOTHING"),
)


def runner(dsn):
    def run(sql, allow_failure=False):
        done = subprocess.run(
            ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-tAX", "-c", sql],
            capture_output=True,
            text=True,
        )
        if done.returncode != 0 and not allow_failure:
            raise SystemExit("psql exited %d on %r\n  %s" % (done.returncode, sql[:80], done.stderr.strip()))
        error = None
        if done.stderr.strip():
            error = done.stderr.strip().splitlines()[0].replace("ERROR:  ", "")
        return done.returncode, done.stdout.strip(), error

    return run


def setup(run):
    run("DROP SCHEMA IF EXISTS %s CASCADE" % SCHEMA)
    run("DROP PUBLICATION IF EXISTS %s" % PUBLICATION)
    run("SELECT pg_drop_replication_slot(%r) FROM pg_replication_slots WHERE slot_name = %r" % (SLOT, SLOT))
    run("CREATE SCHEMA %s" % SCHEMA)
    for name, columns, alter in ARMS:
        run("CREATE TABLE %s.%s (%s)" % (SCHEMA, name, columns))
        if name == "pk_index":
            run("CREATE UNIQUE INDEX pk_index_uq ON %s.%s (b)" % (SCHEMA, name))
        if alter:
            run("ALTER TABLE %s.%s %s" % (SCHEMA, name, alter))
    run("CREATE PUBLICATION %s FOR TABLES IN SCHEMA %s" % (PUBLICATION, SCHEMA))
    run("SELECT pg_create_logical_replication_slot(%r, 'pgoutput')" % SLOT)


def catalog(run):
    _code, out, _err = run(
        "SELECT c.relname || '|' || c.relreplident::text || '|' ||"
        " (SELECT count(*) FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary)"
        " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = '%s' AND c.relkind = 'r' ORDER BY c.relname" % SCHEMA
    )
    got = {}
    for line in out.splitlines():
        name, ident, pk = line.strip().split("|")
        got[name] = {"replica_identity": ident, "has_primary_key": int(pk) > 0}
    return got


def dml(run):
    """One of each statement per arm. A refusal is the measurement, not an error."""
    got = {}
    for name, _columns, _alter in ARMS:
        arm = {}
        statements = (
            ("insert", "INSERT INTO %s.%s (a, b) VALUES (1, 'one')" % (SCHEMA, name)),
            ("update", "UPDATE %s.%s SET b = 'uno' WHERE a = 1" % (SCHEMA, name)),
            ("delete", "DELETE FROM %s.%s WHERE a = 1" % (SCHEMA, name)),
        )
        for op, sql in statements:
            code, _out, error = run(sql, allow_failure=True)
            arm[op] = {"accepted": code == 0, "error": error}
        got[name] = arm
    return got


def drain(run):
    """Every message on the slot, as a list of kind and tuple tag per table."""
    _code, out, _err = run(
        "SELECT encode(data, 'hex') FROM pg_logical_slot_get_binary_changes("
        "%r, NULL, NULL, 'proto_version', '1', 'publication_names', %r)" % (SLOT, PUBLICATION)
    )
    messages = [bytes.fromhex(line.strip()) for line in out.splitlines() if line.strip()]
    relations = {}
    per_table = {}
    for message in messages:
        kind = chr(message[0])
        if kind == "R":
            oid = int.from_bytes(message[1:5], "big")
            relations[oid] = message[5:].split(b"\x00")[1].decode()
        elif kind in "IUD":
            oid = int.from_bytes(message[1:5], "big")
            name = relations.get(oid, str(oid))
            tag = chr(message[5]) if len(message) > 5 else ""
            per_table.setdefault(name, []).append(kind + (tag if tag in "NKO" else "?"))
    return len(messages), per_table


def teardown(run):
    run("SELECT pg_drop_replication_slot(%r) FROM pg_replication_slots WHERE slot_name = %r" % (SLOT, SLOT))
    run("DROP PUBLICATION IF EXISTS %s" % PUBLICATION)
    run("DROP SCHEMA IF EXISTS %s CASCADE" % SCHEMA)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    args = ap.parse_args(argv)
    run = runner(args.dsn)

    _code, wal_level, _err = run("SHOW wal_level")
    if wal_level != "logical":
        raise SystemExit("wal_level is %r and this measurement needs logical" % wal_level)

    setup(run)
    cat = catalog(run)
    statements = dml(run)
    total, per_table = drain(run)
    teardown(run)

    arms = [name for name, _c, _a in ARMS]
    if sorted(cat) != sorted(arms):
        raise SystemExit("the catalog answered for %r and the arms are %r" % (sorted(cat), sorted(arms)))

    measured = {
        "server_wal_level": wal_level,
        "arms": arms,
        "catalog": cat,
        "statements": statements,
        "wal_messages_total": total,
        "wal_per_table": per_table,
        "measured": ["catalog", "statements", "wal_per_table"],
    }
    os.makedirs("measurements", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(measured, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print("wrote %s, %d messages on the slot" % (OUT, total))
    for name in arms:
        print("  %-18s identity=%s  wal=%s" % (name, cat[name]["replica_identity"], per_table.get(name, [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
