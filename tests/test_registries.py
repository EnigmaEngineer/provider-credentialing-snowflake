"""Checks on the source definitions.

Each source carries the encoding its bytes are to be read with. That is the one
field here that came out of a measurement rather than a preference, so it is
the one the checks are about.
"""

import dataclasses

from screening import registries


def check_every_source_is_named_once():
    keys = [s.key for s in registries.SOURCES]
    assert len(keys) == len(set(keys)), keys
    assert set(keys) == set(registries.BY_KEY), (keys, sorted(registries.BY_KEY))


def check_every_source_declares_an_encoding_and_a_url_and_a_sentence():
    for s in registries.SOURCES:
        assert s.encoding, s.key
        assert s.url.startswith("https://"), (s.key, s.url)
        assert s.local_name, s.key
        assert s.what.endswith("."), (s.key, s.what)


def check_the_enrollment_extract_is_not_declared_as_utf8():
    # Eleven of its rows are not valid UTF-8. Declaring it as UTF-8 aborts the
    # load and declaring a lenient decode damages the name fields the fallback
    # match tiers compare.
    s = registries.source("cms_enrollment")
    assert s.encoding == "cp1252", s.encoding


def check_the_exclusion_list_is_declared_with_its_byte_order_mark():
    s = registries.source("leie")
    assert s.encoding == "utf-8-sig", s.encoding


def check_an_archived_source_names_the_member_and_a_plain_one_does_not():
    for s in registries.SOURCES:
        if s.local_name.endswith(".zip"):
            assert s.member, s.key
        else:
            assert s.member is None, s.key


def check_asking_for_a_source_that_does_not_exist_raises():
    # The alternative is a lookup returning None and the caller reading an
    # attribute off it three lines later.
    try:
        registries.source("not_a_registry")
    except KeyError as exc:
        assert "not_a_registry" in str(exc), str(exc)
    else:
        raise AssertionError("an unknown source key was accepted")


def check_no_source_declares_a_lenient_decode():
    for s in registries.SOURCES:
        assert "replace" not in s.encoding, s.key
        assert "ignore" not in s.encoding, s.key


def check_a_source_cannot_be_edited_after_it_is_defined():
    # The definitions are read by every script and a caller that could retune
    # an encoding in passing is a caller that can make one script disagree
    # with another about what the bytes mean.
    s = registries.source("leie")
    try:
        s.encoding = "utf-8"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("a source encoding was reassigned")
    assert registries.source("leie").encoding == "utf-8-sig"
