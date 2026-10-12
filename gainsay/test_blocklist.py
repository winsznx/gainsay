import pytest

from gainsay.blocklist import (
    BlocklistedDocument,
    assert_not_blocklisted,
    normalize_docket_number,
)


@pytest.mark.parametrize(
    "docket_number",
    ["1:22-cv-01461", "22-cv-01461", "22-cv-1461", "1:22-CV-01461", "22cv1461"],
)
def test_refuses_mata_sanctions_opinion_in_any_docket_format(docket_number):
    with pytest.raises(BlocklistedDocument, match="ECF 54"):
        assert_not_blocklisted("nysd", docket_number, 54)


def test_court_match_is_case_insensitive():
    with pytest.raises(BlocklistedDocument):
        assert_not_blocklisted("NYSD", "1:22-cv-01461", 54)


@pytest.mark.parametrize(
    ("court", "docket_number", "entry_number"),
    [
        ("nysd", "1:22-cv-01461", 21),
        ("nysd", "1:22-cv-01462", 54),
        ("nyed", "1:22-cv-01461", 54),
    ],
)
def test_allows_other_entries(court, docket_number, entry_number):
    assert_not_blocklisted(court, docket_number, entry_number)


def test_rejects_unparseable_docket_number():
    with pytest.raises(ValueError):
        normalize_docket_number("not a docket")


def test_the_gauthier_rulings_are_blocked():
    import pytest
    from gainsay.blocklist import BlocklistedDocument, assert_not_blocklisted
    for entry in (42, 44, 48):
        with pytest.raises(BlocklistedDocument):
            assert_not_blocklisted("txed", "1:23-cv-00281", entry)
    assert_not_blocklisted("txed", "1:23-cv-00281", 41)
