# Where these fixtures came from

`leie_sample.csv` is eight rows built by `scripts/make_fixture.py` out of the
real exclusion list. The rows are chosen by the repository's own classifier, so
the fixture covers the cases the code distinguishes rather than the cases
whoever wrote it remembered.

Two things were changed on the way in.

Every date of birth was replaced with a constructed value. A name beside a date
of birth is the pair this project masks in the warehouse, and committing that
pair here would publish exactly what the masking is for. The tier two key
collision in the fixture is therefore constructed as well, because two rows can
only share a key once their dates of birth are the same and both of those are
substitutes.

Every street address, city and postal code was cleared for the same reason.

One row is wholly constructed and labelled `CONSTRUCTED CHECKDIGIT`. No record
in the real file carries an NPI that fails its check digit, so without that row
the malformed branch of the classifier is never reached by anything.

`infra_bad/bad.tf` is written to be broken. Every rule that grades the
configuration has to fire on it, which is what stops a set of passing rules
from being a set of rules pointed at nothing. Nothing deploys from it.
