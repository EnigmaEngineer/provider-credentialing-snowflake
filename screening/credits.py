"""What a monthly cycle costs, derived from the configuration and the vendor's own page.

There is no account, so nothing here is a measurement of consumption. Every
figure is derived from two things that are both committed: the sizes and
cluster counts in `infra/`, and the billing rules Snowflake publishes. A rate
read off a page is a fact about the vendor. A number of seconds a stage takes
is a fact about data nobody has loaded, and it is not here.

So this publishes a FLOOR and a CEILING and names the gap between them rather
than estimating a point inside it.

The floor is exact and it is the part nobody computes. Billing carries a
60 second minimum every time a warehouse starts, so a cycle pays that minimum
once per resumption whether or not it does a second of work. The number of
resumptions is a property of the cycle graph and of auto_suspend, not of the
data, which is what makes it derivable here.

The ceiling is the per hour rate with the cluster count applied. A
multi cluster warehouse bills every running cluster at the full size rate, so
a warehouse whose maximum is two has twice the ceiling its size suggests.

Every rule below carries the sentence it came from and the page it is on. A
lookup raises on a key it does not hold, so nothing here can rest on a default
nobody read.
"""

from dataclasses import dataclass

OVERVIEW = "https://docs.snowflake.com/en/user-guide/warehouses-overview"
CONSIDERATIONS = "https://docs.snowflake.com/en/user-guide/warehouses-considerations"
MULTICLUSTER = "https://docs.snowflake.com/en/user-guide/warehouses-multicluster"
MONITORS = "https://docs.snowflake.com/en/user-guide/resource-monitors"


class NotSourced(Exception):
    """Raised for a billing fact nobody read off a page."""


@dataclass(frozen=True)
class Sourced:
    value: object
    quote: str
    url: str


# Credits per hour by warehouse size. The page calls this column
# "Credits / hour (Gen1 warehouses)" and says the figures are for the first
# generation of Snowflake standard warehouses. Gen2 rates are in a separate
# consumption table that is a PDF, which was not read, so a Gen2 account would
# make every figure here wrong by an amount nothing in this repository knows.
# That limitation is published rather than assumed away.
GENERATION = Sourced(
    "Gen1",
    "Credits / hour (Gen1 warehouses)",
    OVERVIEW,
)

RATE_PER_HOUR = {
    "XSMALL": 1,
    "SMALL": 2,
    "MEDIUM": 4,
    "LARGE": 8,
    "XLARGE": 16,
    "XXLARGE": 32,
    "XXXLARGE": 64,
    "X4LARGE": 128,
    "X5LARGE": 256,
    "X6LARGE": 512,
}

MINIMUM_BILLED_SECONDS = Sourced(
    60,
    "Snowflake utilizes per-second billing (with a 60-second minimum each time the warehouse starts)",
    OVERVIEW,
)

PER_SECOND_AFTER_THE_MINIMUM = Sourced(
    True,
    "After the first 60 seconds, all subsequent billing for a running warehouse is per-second",
    CONSIDERATIONS,
)

# The sentence that makes a resumption count worth deriving. A restart inside
# the first window is charged a fresh minimum, so resumptions add rather than
# overlapping.
A_RESTART_PAYS_AGAIN = Sourced(
    True,
    "If a warehouse runs for 61 seconds, shuts down, and then restarts and runs for less than 60 seconds, it is billed for 121 seconds (60 + 1 + 60).",
    CONSIDERATIONS,
)

# And the sentence that makes a low auto_suspend a cost decision rather than a
# thrift one.
SUSPENDING_TOO_EAGERLY_COSTS = Sourced(
    True,
    "each time it resumes, you are billed for the minimum credit usage (that is, 60 seconds)",
    CONSIDERATIONS,
)

CLUSTERS_BILL_SEPARATELY = Sourced(
    True,
    "the number of credits billed is calculated based on the warehouse size and the number of clusters that run within the time period",
    OVERVIEW,
)

QUOTA_IS_PER_INTERVAL = Sourced(
    True,
    "Credit quota specifies the number of Snowflake credits allocated to the monitor for the specified frequency interval.",
    MONITORS,
)

# Snowpipe is serverless. Its credits are not on the warehouse rate table at
# all, so the landing stage's cost cannot be derived from anything read here.
# Saying so is the answer rather than putting a warehouse rate against it.
SNOWPIPE_IS_NOT_ON_THIS_TABLE = Sourced(
    None,
    "not found on the four pages read",
    OVERVIEW,
)

SOURCED_FACTS = {
    "generation": GENERATION,
    "minimum_billed_seconds": MINIMUM_BILLED_SECONDS,
    "per_second_after_the_minimum": PER_SECOND_AFTER_THE_MINIMUM,
    "a_restart_pays_again": A_RESTART_PAYS_AGAIN,
    "suspending_too_eagerly_costs": SUSPENDING_TOO_EAGERLY_COSTS,
    "clusters_bill_separately": CLUSTERS_BILL_SEPARATELY,
    "quota_is_per_interval": QUOTA_IS_PER_INTERVAL,
    "snowpipe_is_not_on_this_table": SNOWPIPE_IS_NOT_ON_THIS_TABLE,
}


def fact(key):
    """A billing rule, or an exception naming the one nobody read."""
    if key not in SOURCED_FACTS:
        raise NotSourced("no sourced billing fact called %r" % (key,))
    return SOURCED_FACTS[key]


def rate_per_hour(size):
    """Credits an hour for one cluster of this size."""
    key = size.upper().replace("-", "").replace("_", "")
    if key not in RATE_PER_HOUR:
        raise NotSourced("no published credit rate for warehouse size %r" % (size,))
    return RATE_PER_HOUR[key]


def ceiling_per_hour(size, max_clusters):
    """Every cluster bills at the full size rate, so the ceiling multiplies."""
    if max_clusters is None or max_clusters < 1:
        raise NotSourced("a warehouse with no cluster count has no derivable ceiling")
    return rate_per_hour(size) * max_clusters


def floor_credits(resumptions, size, clusters=1):
    """What a resumption costs before it does any work.

    This is the part of a cycle's bill that does not depend on the data. Every
    start is charged the published minimum, and a restart inside the window is
    charged again rather than absorbed.
    """
    if resumptions < 0:
        raise NotSourced("a resumption count is not negative")
    seconds = resumptions * MINIMUM_BILLED_SECONDS.value
    return seconds * rate_per_hour(size) * clusters / 3600.0


def resumption_bounds(stages_on_the_warehouse):
    """How many times one warehouse starts during one cycle, bracketed.

    The lower bound is one. Every stage on the warehouse runs inside a single
    resumption when each gap between them is shorter than auto_suspend.

    The upper bound is the stage count. Every gap exceeds auto_suspend and each
    stage pays its own minimum.

    Which end a deployment sits at is decided by how long each stage takes,
    which is a fact about data nobody has loaded. So this returns both and the
    manifest publishes both.
    """
    if stages_on_the_warehouse < 1:
        return (0, 0)
    return (1, stages_on_the_warehouse)
