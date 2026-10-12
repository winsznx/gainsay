import pytest

from gainsay.names import names_match


@pytest.mark.parametrize(
    ("cited", "found"),
    [
        ("Al Israel Airlines, Ltd. v. Tseng", "El Al Israel Airlines, Ltd. v. Tsui Yuan Tseng"),
        ("Kaiser Steel Corp. v. W.S. Ranch Co.", "Kaiser Steel Corp. v. W. S. Ranch Co."),
        ("Doe v. United States", "John Doe v. United States"),
        ("Varghese v. China Southern Airlines Co., Ltd.", "Varghese v. China Southern Airlines Co."),
        ("In re Air Crash Disaster Near New Orleans, La.", "In Re Air Crash Disaster Near New Orleans"),
        ("Zicherman v. Korean Air Lines Co.", "Zichermann v. Korean Air Lines Co."),
        ("Martinez v. Delta Airlines, Inc.", "Martinez v. Delta Air Lines, Inc."),
        (
            "In re Air Crash Disaster Near New Orleans, La.",
            "In re AIR CRASH DISASTER NEAR NEW ORLEANS, LOUISIANA ON JULY 9, 1982. "
            "Luis Alberto TRIVELLONI-LORENZI v. PAN AMERICAN WORLD AIRWAYS, INC.",
        ),
    ],
)
def test_same_parties_match(cited, found):
    assert names_match(cited, found)


@pytest.mark.parametrize(
    ("cited", "found"),
    [
        ("Doe v. United States", "Smith v. United States"),
        ("Miller v. United Airlines, Inc.", "Miller v. Smith"),
        ("Varghese v. China Southern Airlines Co., Ltd.", "Hopkins v. Airtran Airways"),
        ("Zicherman v. Korean Air Lines Co.", "Zicherman v. Delta Air Lines"),
        ("In re Air Crash Disaster Near New Orleans, La.", "In re Air Crash at Dallas/Fort Worth Airport"),
        ("Peterson v. Iran Air", "Peterson v. Islamic Republic of Iran"),
    ],
)
def test_different_parties_do_not_match(cited, found):
    assert not names_match(cited, found)


def test_names_with_only_generic_words_fall_back_to_whole_name():
    assert names_match("United States v. United States", "United States v. United States")
    assert not names_match("People v. State", "United States v. America")


@pytest.mark.parametrize(
    ("cited", "found"),
    [
        ("De La Fuente v. DCI Telecomms., Inc.", "De La Fuente v. DCI Telecommunications, Inc."),
        ("Advanced Battery Techs., Inc. v. Zhiguo Fu", "Advanced Battery Technologies, Inc. v. Zhiguo Fu"),
        ("Olive Grp. N. Am. LLC v. Afghanistan Int'l Bank", "Olive Group North America LLC v. Afghanistan International Bank"),
        ("Huebner v. Midland Credit Mgmt., Inc.", "Huebner v. Midland Credit Management, Inc."),
    ],
)
def test_bluebook_abbreviations_match_the_words_they_shorten(cited, found):
    assert names_match(cited, found)


def test_short_abbreviation_prefixes_do_not_match_everything():
    assert not names_match("Ash v. United States", "Ashcroft v. United States")


@pytest.mark.parametrize(
    ("cited", "found"),
    [
        ("Reed v. United Transp. Union", "Reed v. United Transportation Union"),
        ("Tucker v. Comm’r", "Tucker v. Commissioner"),
        ("United States v. American Tel. & Tel. Co.", "United States v. American Telephone & Telegraph Co."),
        ("Wyoming v. USDA", "Wyoming v. United States Department of Agriculture"),
        ("Johnson v. SEC", "Patricia A. Johnson v. Securities and Exchange Commission"),
    ],
)
def test_contractions_and_acronyms_match(cited, found):
    assert names_match(cited, found)


def test_acronym_must_spell_the_other_party():
    assert not names_match("Wyoming v. EPA", "Wyoming v. United States Department of Agriculture")
