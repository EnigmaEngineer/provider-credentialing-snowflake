-- The credentialing application's own database, as a source system rather than
-- as a warehouse layer.
--
-- This is the operational side of the problem. A health system runs a
-- credentialing workflow in an application like this one, and the screening
-- platform reads it rather than owning it. No public data set of credentialing
-- applications exists, so everything this file describes is generated.
--
-- Two things in here are not arbitrary and both come out of what replication
-- can see.
--
-- Every table carries a primary key. A table without one cannot be published
-- for deletes at all. Postgres refuses the DELETE rather than replicating a
-- row nobody can identify.
--
-- Two tables declare REPLICA IDENTITY FULL. Under the default identity a
-- delete reaches the write ahead log carrying the primary key and nothing
-- else, which is enough to find the row again only if the destination keyed on
-- the same column. The two tables below are the ones where a delete the
-- warehouse misses changes a screening answer, so they publish the whole old
-- row. The measurement behind that choice is in measurements/replication.json.

CREATE SCHEMA IF NOT EXISTS credentialing;

SET search_path TO credentialing;

CREATE TABLE provider (
    provider_id       integer PRIMARY KEY,
    npi               text,
    last_name         text,
    first_name        text,
    middle_name       text,
    business_name     text,
    date_of_birth     date,
    provider_type     text NOT NULL CHECK (provider_type IN ('individual', 'organization')),
    primary_specialty text,
    created_at        timestamptz NOT NULL,
    updated_at        timestamptz NOT NULL
);

-- The NPI is text and nullable on purpose. An applicant can be in the
-- workflow before the registry has issued one, and the registry's own files
-- write an absent identifier as the character zero rather than as nothing.
-- Storing it as a number would turn both of those into 0 and a join on 0
-- matches every other row that had no identifier either.
COMMENT ON COLUMN provider.npi IS
    'National Provider Identifier as published, ten digits. NULL when none has been issued.';

CREATE TABLE facility (
    facility_id integer PRIMARY KEY,
    name        text NOT NULL,
    state       text NOT NULL
);

CREATE TABLE application (
    application_id   integer PRIMARY KEY,
    provider_id      integer NOT NULL REFERENCES provider (provider_id),
    facility_id      integer NOT NULL REFERENCES facility (facility_id),
    application_type text NOT NULL CHECK (application_type IN ('initial', 'recredential')),
    status           text NOT NULL,
    submitted_on     date NOT NULL,
    decided_on       date
);

CREATE TABLE license (
    license_id     integer PRIMARY KEY,
    provider_id    integer NOT NULL REFERENCES provider (provider_id),
    state          text NOT NULL,
    license_number text NOT NULL,
    issued_on      date NOT NULL,
    expires_on     date NOT NULL,
    status         text NOT NULL
);

CREATE TABLE verification (
    verification_id integer PRIMARY KEY,
    application_id  integer NOT NULL REFERENCES application (application_id),
    source          text NOT NULL,
    requested_at    timestamptz NOT NULL,
    completed_at    timestamptz,
    result          text
);

CREATE TABLE committee_decision (
    decision_id    integer PRIMARY KEY,
    application_id integer NOT NULL REFERENCES application (application_id),
    meeting_on     date NOT NULL,
    decision       text NOT NULL CHECK (decision IN ('approved', 'denied', 'deferred')),
    effective_from date,
    effective_to   date
);

-- A rescinded committee decision is deleted in this application rather than
-- marked. If the warehouse keeps the row, the screening model reads an
-- approved provider who is not approved, which clears somebody who belongs in
-- the review queue. That is the one direction of error this platform exists to
-- prevent, so this table publishes the whole old row on a delete.
ALTER TABLE committee_decision REPLICA IDENTITY FULL;

-- A deleted licence is the same shape of problem one step further out. A
-- provider cleared on a licence that no longer exists is cleared on nothing.
ALTER TABLE license REPLICA IDENTITY FULL;

CREATE INDEX provider_npi_idx ON provider (npi);
CREATE INDEX application_provider_idx ON application (provider_id);
CREATE INDEX license_provider_idx ON license (provider_id);

-- The publication is what the connector reads. It is created here rather than
-- left to whoever sets up the connector, because a table outside it does not
-- replicate and nothing downstream reports its absence. The warehouse simply
-- never sees that table and every model over it returns no rows.
--
-- Publishing a table also takes something away from this application. A
-- published table with no replica identity refuses the UPDATE and the DELETE,
-- and the error is raised here rather than in the warehouse. Measured, with
-- the message, in measurements/replication.json.
CREATE PUBLICATION credentialing_pub FOR TABLES IN SCHEMA credentialing;
