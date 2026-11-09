# Provider credentialing and exclusion screening

A health system cannot bill for a clinician who appears on the federal
exclusion list, and it has to check every active provider against that list at
least monthly. This repository is the screening half of that problem: the
registries, the warehouse they load into, and the matching that decides which
hits a person has to look at.

```
python3 scripts/fetch.py && python3 scripts/profile_registries.py
```

## What is real and what is synthetic

The registries are real public files, downloaded by `scripts/fetch.py` and not
committed. The OIG exclusion list, the NPI registry weekly incremental, the NPI
deactivation report and the Medicare public enrollment extract all come from
their publishers at the URLs in `screening/registries.py`.

The credentialing application itself is synthetic and does not exist yet. A
real one holds application status, documents and committee dates, and no such
data is public. When it arrives it will be generated, and every figure drawn
from it will say so at the point it is used rather than in a note further down.

Nothing here has run against Snowflake. The configuration under `infra/` is
validated and formatted against the provider schema and has never been applied,
because this project has no Snowflake account yet. No number in this file comes
from a warehouse.

## What the exclusion list actually contains

The design below rests on one claim about the source data, so the claim is
measured first. Every figure in this section is read out of
`measurements/registries.json`, which `scripts/profile_registries.py` writes.

| Figure | Count |
|---|---|
| exclusion records | 84093 |
| records whose NPI column holds the character zero | 75169 |
| records with an NPI that passes its check digit | 8924 |
| distinct NPIs among those records | 8743 |
| NPIs appearing on more than one record | 177 |
| most records sharing one NPI | 3 |

The NPI column is populated on every row. On 75169 of them the value is the
single character zero, which is how this file says it has no NPI. That is not a null.
A column typed as a number holds a zero instead. A join on it matches nothing
and raises no error. And a check asking whether the column is populated
answers yes for the whole file.

Not one of the 8924 real NPIs fails its check digit.

### Which match tier can reach a record at all

| Reachable by | Count |
|---|---|
| exact NPI | 8924 |
| exact name and date of birth | 71439 |
| name and state only, an individual | 861 |
| name and state only, a business | 2869 |

Only the first tier may clear a provider without a person looking, so 8924 of
84093 records are auto clearable at best. The rest reach a human by design. The
last two rows are a floor rather than a tuning problem: 3730 records carry
neither a usable NPI nor a date of birth, so no threshold anywhere reaches
them.

### What the fallback key is worth

| Figure | Count |
|---|---|
| tier two keys formable | 78743 |
| keys held by more than one record | 997 |
| records sitting on a shared key | 2020 |
| most records sharing one key | 4 |

A key held by two records cannot clear either of them. That is a property of
the key and it is measured here before anything is matched against it, because
the same key has to separate rows against two and a half million enrolled
providers later.

## The other registries

| Figure | Count |
|---|---|
| enrollment extract rows | 3030023 |
| enrollment rows that are not valid UTF-8 | 11 |
| distinct NPIs in the enrollment extract | 2576755 |
| exclusion NPIs also in the enrollment extract | 15 |
| deactivated NPIs published | 360673 |
| exclusion NPIs also deactivated | 951 |
| registry weekly records | 31562 |
| weekly records with no entity type code | 711 |

Eleven rows of three million carry bytes that are not valid UTF-8. A strict
load aborts on them. A lenient load replaces the character and finishes, and
the field those bytes sit in is a provider name, which is what the fallback
tiers compare. So the encoding is declared per source in
`screening/registries.py` and the enrollment file format in `infra/load.tf`
names `WINDOWS1252` and leaves character replacement off.

The enrollment extract carries no status, termination or end date column. An
NPI appearing in it is an NPI appearing in it. Reading those 15 as currently
enrolled providers would need a source this project does not have, and
`screening/cms.py` records that as a constant so a later model cannot quietly
assume otherwise.

## Architecture

```
  OIG exclusions  NPI registry  NPI deactivations  Medicare enrollment
        |              |              |                    |
        +--------------+------+-------+--------------------+
                              |
                      cloud storage prefix
                              |
                  external stage, one file format
                      per source encoding
                              |
                 SCREENING_RAW.REGISTRY  <-- pipe, auto ingest
                              |
             SCREENING_ANALYTICS  staging -> marts
                              |
                  +-----------+-----------+
                  |                       |
          exact identifier only      everything else
            cleared without a         reaches a person
             person looking
```

Four account roles rather than one. Loading writes the raw layer and reads
nothing in analytics. Transforming reads raw and writes analytics. Analysis
reads the marts with identifiers redacted. Review sees identifiers whole for
one facility. The roles exist in `infra/roles.tf` and what each one can do is
in `infra/grants.tf`, because a role is only a name until something is granted
to it.

## The gate on the configuration

`terraform validate` reads a value and asks whether the provider accepts it.
Almost every argument that decides whether a Snowflake object does anything is
optional, so it cannot fail on an argument nobody wrote. A warehouse with no
`auto_suspend` runs on the account default. A resource monitor with only a name
has no quota, no triggers and no recipients. A grant naming neither
`privileges` nor `all_privileges` grants nothing. A pipe without `auto_ingest`
waits to be asked. Every one of those validates.

So `screening/tfrules.py` carries one rule per capability and each rule fires
when the element that makes the capability real is absent. The rules run in the
test suite rather than as a plan, because the suite runs on a clone with no
cloud account. `tests/fixtures/infra_bad/bad.tf` is a configuration written to
break every one of them, and the suite fails if any rule stays silent on it.

Two defects in this configuration came out of `terraform validate` and neither
was a wrong value. The provider cannot connect on a warehouse this
configuration creates, which is a cycle. And `frequency` and `start_timestamp`
on a resource monitor are both listed as optional attributes while the provider
refuses either one alone, with the pairing stated in the description text
inside the schema rather than in its required flag. I read the required flags
first and missed the second one entirely.

## Running the checks

```
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 tests/run_all.py
```

The suite needs no downloads. Every check reads a committed fixture, and
`tests/fixtures/PROVENANCE.md` says how each one was built and what was changed
on the way in.

It does need both requirements files. The second one carries a parser used to
grade the configuration reader against an independent reading of the same
files. Those checks fail rather than skip when it is missing, because a check
that goes quiet without its dependency reports clean on a machine that cannot
run it.

## Known limitations

Nothing has been applied to Snowflake. The configuration is correct against the
provider schema version it pins and unproven against an account. There is no
Snowflake account identifier and no service user for this project yet, so the
deploy workflow has nothing to authenticate as.

The workflow in `.github/workflows/ci.yml` has never executed. The checks on it
read the names of the scripts it calls and the arguments it passes. They cannot
see whether the state one step leaves is the state the next one needs, which is
the defect that kind of file usually has.

The monthly NPI full file is 1079 MB and nothing here downloads it. The weekly
incremental shares its record layout, so the readers and the eventual staging
models are written against the weekly one and the full file is a larger input
to the same code. That is an assumption about the layout and it has not been
checked against the full file.

The matching is not built. The counts above say what each tier can reach and
say nothing about precision or recall, because neither has been measured and
there is no labelled sample yet.

The pipe needs a notification integration that does not exist, so it would fail
a plan for a second reason beyond the missing account.
