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


@pytest.mark.parametrize(
    ("cited", "found"),
    [
        ("Bell Atl. Corp. v. Twombly", "Bell Atlantic Corp. v. Twombly"),
        ("Am. Gen. Life Ins. Co. v. Pac. Mut. Co.", "American General Life Insurance Co. v. Pacific Mutual Co."),
    ],
)
def test_short_bluebook_abbreviations_match(cited, found):
    assert names_match(cited, found)


def test_bluebook_abbreviations_and_acronyms_match_the_full_caption():
    pairs = [
        ("Chevron U.S.A. v. Natural Res. Def. Council", "Chevron U. S. A. Inc. v. Natural Resources Defense Council, Inc."),
        ("Soc’y of the Holy Transfiguration Monastery, Inc. v. Archbishop Gregory of Denver",
         "Society of the Holy Transfiguration Monastery, Inc. v. Archbishop Gregory of Denver, Colorado"),
        ("G. D. Searle & Co. v. Charles Pfizer & Co.", "G. D. Searle & Co. v. Chas. Pfizer & Co., Inc."),
        ("Picking v. Pennsylvania Railway", "Picking v. Pennsylvania R. Co."),
        ("Columbia Steel Casting Co. v. Portland GE", "Columbia Steel Casting Co. v. Portland General Electric Co."),
        ("Cook, Perkiss & Liehe, Inc. v. N. Cal. Collection Serv., Inc.",
         "Cook, Perkiss And Liehe, Inc. v. Northern California Collection Service Inc."),
        ("Local Joint Exec. Bd. of Culinary/Bartender Trust Fund v. Las Vegas Sands, Inc.",
         "Local Joint Executive Board of Culinary/Bartender Trust Fund v. Las Vegas Sands, Inc."),
    ]
    for cited, found in pairs:
        assert names_match(cited, found), cited


def test_a_different_case_or_a_misspelled_party_still_does_not_match():
    assert not names_match("Spinella v. Pearce", "Ricardo Jalil v. Avdel Corporation")
    assert not names_match("Sims v. Aherns", "Sims v. Ahrens")
    assert not names_match("Vela v. City of Houston", "United States v. Andreas")


def test_a_numbered_short_form_matches_its_case():
    assert names_match("Ezell II", "Ezell v. City of Chicago")


def test_compass_and_apostrophe_contractions_match():
    assert names_match("McCaskey v. Cont’l Airlines, Inc.", "McCaskey v. Continental Airlines, Inc.")
    assert names_match("Redl v. Nw. Airlines, Inc.", "Redl v. Northwest Airlines, Inc.")
