"""Who may read what, stated once so two enforcements can be compared against it.

The warehouse enforces this with masking policies and a row access policy. The
only thing that can evaluate those is the account, and nothing here has one. So
the design lives in this module as data, the configuration in infra/policies.tf
is graded against it, and scripts/measure_access.py applies the same data to the
models in duckdb and records what each role actually ends up seeing.

Two ideas carry most of the work.

A quantity is protected, not a column. Masking the identifier column on the
review queue leaves the identifier recoverable from the matched record, because
the tier one join is an equality between the two. The same holds for the name
and date of birth triple against the tier two key, which is those three values
concatenated. So a relation declares every column set that recovers a quantity
and the withheld set is the closure over all of them. A list of column names
somebody keeps current goes stale on the day a model gains a derived column.

A recovery can be conditional. matched_npi recovers the provider's own
identifier on tier one rows and names a different person's record on the others.
A policy that masks the column outright costs a reviewer the record identifier
on every row. The provider's conditional masking form takes the deciding column
as a second argument, which is what makes the per row answer expressible, so a
recovery set carries the condition it holds under.
"""

from dataclasses import dataclass, field

from . import match

# The two things worth withholding. Both are about a provider in the
# credentialing workflow rather than about somebody on the exclusion list,
# because the exclusion list is published by the federal government and
# redacting it here would protect nothing.
PROVIDER_IDENTIFIER = "provider_identifier"
PROVIDER_IDENTITY = "provider_identity"

QUANTITIES = (PROVIDER_IDENTIFIER, PROVIDER_IDENTITY)


@dataclass(frozen=True)
class Recovery:
    """One column set that recovers a quantity, and when it does.

    `whole` is False when the set gives back some of the quantity and not all
    of it. The third tier joins on the surname and the given name and reaches
    rows whose dates of birth disagree, so its key gives back two of the three
    fields. Two of three is still a person in a file of five hundred, so a
    partial recovery withholds the column exactly like a whole one. It is
    recorded separately because the measurement counts them separately and a
    design that called them the same thing could not be graded against it.
    """

    quantity: str
    columns: tuple
    # None means the set recovers the quantity on every row. A string names the
    # column whose value decides, and `holds_when` the values it decides for.
    decided_by: str = None
    holds_when: tuple = ()
    whole: bool = True

    @property
    def is_conditional(self):
        return self.decided_by is not None

    @property
    def measured_as(self):
        """The counter name the measurement increments for this recovery."""
        suffix = "recovers_the_identity" if self.quantity == PROVIDER_IDENTITY else "recovers_the_identifier"
        if not self.whole:
            suffix = "recovers_the_name_only"
        return "%s_%s" % (self.columns[0], suffix)


@dataclass(frozen=True)
class Relation:
    """A published relation and what can be read out of it."""

    name: str
    columns: tuple
    recoveries: tuple
    # The column a row access policy filters on. None means the relation
    # carries no row level restriction and every role that can read it at all
    # reads every row.
    scope_column: str = None

    def recoveries_for(self, quantity):
        return tuple(r for r in self.recoveries if r.quantity == quantity)


@dataclass(frozen=True)
class Role:
    """What one role may read."""

    name: str
    reads: tuple
    sees_whole: tuple = ()
    # True when the role reads every row of every relation it can read.
    reads_every_row: bool = True
    scope_values: tuple = field(default_factory=tuple)


# The queue a person works. One row per provider, carrying the strongest tier
# that reached them, so this is the relation a reviewer opens.
REVIEW_QUEUE = Relation(
    name="review_queue",
    columns=(
        "provider_id",
        "npi",
        "npi_is_absent",
        "last_name",
        "first_name",
        "date_of_birth",
        "tier",
        "tier_rank",
        "records_matched",
        "distinct_records_matched",
        "cleared_without_review",
        "facility_id",
    ),
    recoveries=(
        Recovery(PROVIDER_IDENTIFIER, ("npi",)),
        Recovery(PROVIDER_IDENTITY, ("last_name", "first_name", "date_of_birth")),
    ),
    scope_column="facility_id",
)

# Pair grained. A reviewer working a decision needs the record a tier reached,
# and the record is where both leaks live.
MATCH_CANDIDATE = Relation(
    name="match_candidate",
    columns=(
        "provider_id",
        "tier",
        "tier_rank",
        "matched_npi",
        "matched_fallback_key",
        "facility_id",
    ),
    recoveries=(
        # The tier one join is p.npi = e.npi, so on a tier one row the matched
        # identifier is the provider's own identifier. Nothing about the column
        # name says so.
        Recovery(PROVIDER_IDENTIFIER, ("matched_npi",), decided_by="tier_rank", holds_when=(1,)),
        # The tier two join forms the key out of the provider's surname, given
        # name and date of birth in that order, pipe separated. So on a tier two
        # row this one column is all three values.
        Recovery(
            PROVIDER_IDENTITY,
            ("matched_fallback_key",),
            decided_by="tier_rank",
            holds_when=(2,),
        ),
        # And the same column on a third tier row. This one was not in the
        # design until the measurement counted it. The condition had been
        # written as the second tier alone, which is what reading the join that
        # forms the key gives you, and the third tier joins on two of its three
        # fields and publishes the key anyway. 51 of 51 pairs.
        Recovery(
            PROVIDER_IDENTITY,
            ("matched_fallback_key",),
            decided_by="tier_rank",
            holds_when=(3,),
            whole=False,
        ),
    ),
    scope_column="facility_id",
)

RELATIONS = (REVIEW_QUEUE, MATCH_CANDIDATE)

# The loader writes the raw layer and reads nothing here. It is in the design
# so a check can assert that, rather than it being true because nobody wrote
# the grant.
LOADER = Role(name="SCREENING_LOADER", reads=())

# The transformer builds these relations, so it reads them whole. A masking
# policy that applied to it would mask the inputs of every model downstream.
TRANSFORMER = Role(
    name="SCREENING_TRANSFORMER",
    reads=("review_queue", "match_candidate"),
    sees_whole=QUANTITIES,
)

# Counts how many providers reach each tier and how many are cleared with
# nobody looking. That question needs no names in it.
ANALYST = Role(
    name="SCREENING_ANALYST",
    reads=("review_queue", "match_candidate"),
    sees_whole=(),
)

# Works the queue. Needs the identity whole, because the job is deciding
# whether this provider is that excluded person, and has no business reading a
# facility they do not work for.
REVIEWER = Role(
    name="SCREENING_REVIEWER",
    reads=("review_queue", "match_candidate"),
    sees_whole=QUANTITIES,
    reads_every_row=False,
    # One facility. The seed carries three and a reviewer assigned all of them
    # would read every row, which is what a row access policy that filters
    # nothing also looks like. The mapping table is what carries this in the
    # account and the design holds the fixture's version of it.
    scope_values=(1,),
)

ROLES = (LOADER, TRANSFORMER, ANALYST, REVIEWER)

# A provider with no live application has no facility, so a row access policy
# keyed on the facility reaches them from no reviewer at all. That is the same
# disappearance as the state tier being unable to reach a provider with no
# licence, and the decision here is the opposite of the one that is cheap to
# write. An unscoped row is visible to every reviewer rather than to none.
#
# The cost is duplicated work on a small bucket. The cost of the other answer
# is a provider nobody is assigned to, screened against nothing and never seen,
# and the platform would not be able to tell that apart from an empty queue.
UNSCOPED_ROWS_GO_TO_EVERY_REVIEWER = True


def match_rank(tier):
    """The rank a tier name carries, from the matching module rather than a copy.

    The rank is what a conditional policy switches on, so it has to be the
    same number the model publishes. Deriving it here keeps one definition of
    the tier order in the repository.
    """
    return match.TIER_ORDER.index(tier) + 1


def relation(name):
    for rel in RELATIONS:
        if rel.name == name:
            return rel
    raise KeyError("no relation named %s in the access design" % name)


def role(name):
    for r in ROLES:
        if r.name == name:
            return r
    raise KeyError("no role named %s in the access design" % name)


def withheld_from(role_obj, relation_obj):
    """Every column this role may not read whole, as the closure over recoveries.

    A column lands here if it appears in any recovery set for a quantity the
    role does not see whole. That is what makes the answer survive a new
    derived column: the column arrives in a recovery set or it recovers
    nothing, and there is a check for the first half.
    """
    out = set()
    for quantity in QUANTITIES:
        if quantity in role_obj.sees_whole:
            continue
        for rec in relation_obj.recoveries_for(quantity):
            out.update(rec.columns)
    return out


def conditionally_withheld_from(role_obj, relation_obj):
    """The withheld columns whose recovery holds on some rows and not others.

    These are the ones a plain masking policy overcharges for. The answer is
    the conditional form, which takes the deciding column as an argument.

    A column can carry more than one conditional recovery, so the condition is
    the union of what each of them holds under. Writing the policy from one of
    them leaves the other rows published, which is the defect the third tier
    turned out to be.
    """
    out = {}
    for quantity in QUANTITIES:
        if quantity in role_obj.sees_whole:
            continue
        for rec in relation_obj.recoveries_for(quantity):
            if not rec.is_conditional:
                continue
            for col in rec.columns:
                decided_by, values = out.get(col, (rec.decided_by, ()))
                if decided_by != rec.decided_by:
                    raise ValueError(
                        "%s on %s is decided by two different columns, so one policy "
                        "cannot express it" % (col, relation_obj.name)
                    )
                out[col] = (decided_by, tuple(sorted(set(values) | set(rec.holds_when))))
    return out


def visible_columns(role_obj, relation_obj):
    """What the role reads unredacted, in the relation's own column order."""
    withheld = withheld_from(role_obj, relation_obj)
    return tuple(c for c in relation_obj.columns if c not in withheld)


def row_is_visible(role_obj, relation_obj, row):
    """Whether one row reaches this role, by the rule the policy body states."""
    if relation_obj.scope_column is None or role_obj.reads_every_row:
        return True
    value = row.get(relation_obj.scope_column)
    if value is None:
        return UNSCOPED_ROWS_GO_TO_EVERY_REVIEWER
    return value in role_obj.scope_values
