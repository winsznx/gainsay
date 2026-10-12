from gainsay.findings import FAIL, NOT_APPLICABLE, PASS, UNVERIFIABLE
from gainsay.opinions import OpinionText
from gainsay.quotes import check_quotes, normalize, split_passages

IQBAL = OpinionText(
    1,
    "020lead",
    "html_with_citations",
    "Rule 8 marks a departure. Threadbare recitals of the elements of a cause of action, "
    "supported by mere conclusory statements, do not suffice. Second, only a complaint "
    "that states a plausible claim for relief survives.",
    [(80, 679)],
)


def test_quote_found_with_page():
    finding = check_quotes(["threadbare recitals of the elements"], [IQBAL], first_page=662)
    assert finding.outcome == PASS
    assert "page 678" in finding.reason


def test_quote_with_ocr_quote_marks_and_brackets_still_matches():
    quote = "[T]hreadbare recitals of the elements of a cause of action, supported by mere ‘conclusory’ statements"
    assert check_quotes([quote], [IQBAL], 662).outcome == PASS


def test_invented_quote_fails_and_names_the_passage():
    quote = (
        "Threadbare recitals of the elements of a cause of action do not suffice. "
        "The tolling effect of the automatic stay on a statute of limitations is a matter of federal law, "
        "and the Montreal Convention does not preempt it in any respect whatsoever."
    ) * 2
    finding = check_quotes([quote], [IQBAL], 662)
    assert finding.outcome == FAIL
    assert "tolling effect" in finding.reason


def test_ellipses_split_passages():
    assert split_passages("Threadbare recitals of the elements . . . do not suffice to state a claim") == [
        "Threadbare recitals of the elements",
        "do not suffice to state a claim",
    ]


def test_no_quotes_or_no_opinion():
    assert check_quotes([], [IQBAL], 662).outcome == NOT_APPLICABLE
    assert check_quotes(["threadbare recitals of the elements"], [], 662).outcome == UNVERIFIABLE


def test_normalize_keeps_offsets_into_the_source():
    text, offsets = normalize("A  “Quoted”—word")
    assert text == "a quoted-word"
    assert offsets[text.index("q")] == 4


def test_bracketed_rewrites_split_the_quote_but_a_bracketed_letter_does_not():
    assert split_passages("the law firm could not have objectively believed [the statements] were true and correct") == [
        "the law firm could not have objectively believed",
        "were true and correct",
    ]
    assert split_passages("[T]hreadbare recitals of the elements") == ["[T]hreadbare recitals of the elements"]
