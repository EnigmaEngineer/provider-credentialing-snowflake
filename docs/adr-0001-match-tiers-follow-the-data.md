# Match tiers follow what the exclusion list actually carries

## Context

Screening a provider against the federal exclusion list sounds like a join on
the national provider identifier. A false negative means billing for an
excluded clinician. A false positive stops a legitimate one from starting work,
which costs a week of revenue per week it lasts. So the matching has to be both
careful and fast, and the obvious design is exact identifier first with softer
fallbacks behind it.

The question that decides how much of the system is the fallback path is how
often the identifier is there at all. I assumed many older records would be
missing it. Measured, it is worse than that and it is missing in a way a schema
cannot see.

## What the data says

Read by `scripts/profile_registries.py`, written to
`measurements/registries.json`.

The exclusion list holds 84093 records. The identifier column is populated on
every single one. On 75169 of them the value is the single character zero.

That matters more than the share does. A null is visible to every tool. A zero
is a value. So a column typed as a number holds a zero. A count of populated
rows returns the whole file. And a join against the provider registry matches
nothing and reports no error. The only thing that can tell a real identifier
from that sentinel is code that knows about the sentinel.

Of the 8924 records that do carry one, none fails its check digit, and 8743 are
distinct. So 177 identifiers sit on more than one record and the worst holds
three. A match on the identifier is one to many.

Splitting the file by what each tier can reach:

| Reachable by | Count |
|---|---|
| exact identifier | 8924 |
| exact name and date of birth | 71439 |
| name and state only, an individual | 861 |
| name and state only, a business | 2869 |

## Decision

Three tiers, and only the first clears a provider without a person looking.

The first tier joins on the identifier and takes the fan out seriously. A
provider with three exclusion records is one provider and three facts about
them, and the review queue shows all three rather than the newest.

The second tier keys on last name, first name and date of birth. 78743 records
can form that key and 997 of those keys are held by more than one record, so
2020 records sit on a key that cannot identify them. Those reach a person even
when the key matches exactly, because a key held by two records clears neither.

The third tier is name within state, and nothing in it is ever cleared
automatically.

3730 records can only ever reach the third tier, because they carry neither an
identifier nor a date of birth. That is a floor on the human queue and not a
threshold anybody can improve. 2869 of those are businesses with no person name
and no date of birth at all, so the second tier is not merely unreliable for
them, it is not expressible.

## What this rules out

It rules out treating the review queue as an exception path. At best 8924 of
84093 exclusion records are auto clearable, so the queue is the main path and
the interface a credentialing specialist works is the product rather than a
fallback screen.

It rules out tuning the way out of the third tier. No similarity threshold
invents a date of birth.

It rules out a single identifier column in the staged model. The sentinel has
to survive the load as a distinguishable thing, which is why the file format in
`infra/load.tf` names an empty null list and the classifier returns three
answers rather than two.

## What is not decided

No threshold exists for the third tier, because precision and recall have not
been measured and there is no labelled sample yet. The counts above say what
each tier can reach and say nothing about how well any of them work.

Whether a business name match is worth attempting at all is open. 2869 records
are businesses reachable only by name and state, and organisation names in
these files disagree with each other. Two records sharing one identifier in
this file spell the same organisation two ways, one of them with the word
therapeutic misspelled.
