from gainsay.extract import clean_text, extract, find_quotes

OCR_PAGE = """Case 1:22-cv-01461-PKC Document 21 Filed 03/01/23 Page 7 of 10

17.

held that the stay may toll the period. Miller v. United Airlines, Inc., 174 F.3d 366, 371-
72 (2d Cir. 1999). In Shaboon v. Egyptair, 2013 IL App (Ist) 111279-U (Ill. App. Ct. 2013),
the court held that state courts have concurrent jurisdiction."""


def test_clean_text_drops_stamps_and_margin_numbers_and_rejoins_pincites():
    text = clean_text(OCR_PAGE)
    assert "Document 21" not in text
    assert "17." not in text
    assert "371-72 (2d Cir. 1999)" in text
    assert "2013 IL App (1st) 111279-U" in text


def test_inner_ocr_quote_mark_does_not_split_block_quote():
    text = 'stating “Congress acted to \'unify the system. “El Al v. Tseng, 525 U.S. 155. It ended."'
    (start, end), = find_quotes(text)
    assert text[start:end].startswith("Congress acted")
    assert text[start:end].endswith("It ended.")


def test_ocr_periods_between_parallel_cites_still_group_one_case():
    text = (
        "The tolling effect of the stay is generally a matter of federal law. "
        "See Kaiser Steel Corp. v. W.S. Ranch Co.. 391 U.S. 593, 598. 88 S. Ct. 1753, "
        "20 L.Ed.2d 835 (1968)."
    )
    extraction = extract(text)
    (citation,) = extraction.citations
    assert citation.pincite == "598"
    assert citation.authority.case_name == "Kaiser Steel Corp. v. W.S. Ranch Co."
    assert citation.authority.reporter_cites == ["391 U.S. 593", "88 S. Ct. 1753", "20 L. Ed. 2d 835"]


def test_bare_citation_sentence_supports_the_sentence_before_it():
    text = (
        "The tolling effect of the stay is generally a matter of federal law. "
        "See Kaiser Steel Corp. v. W.S. Ranch Co., 391 U.S. 593, 598 (1968)."
    )
    (citation,) = extract(text).citations
    assert citation.proposition == "The tolling effect of the stay is generally a matter of federal law."


def test_id_points_at_the_previous_case_even_with_a_low_pincite():
    text = (
        "Congress meant to unify the system. El Al Israel Airlines, Ltd. v. Tseng, 525 U.S. 155, 161, "
        "119 S.Ct. 662, 142 L.Ed.2d 576 (1999). Congress sought to give passengers certainty "
        "in the event of an accident. Id. at 166, 119 S. Ct. 662."
    )
    tseng, id_cite = extract(text).citations
    assert id_cite.kind == "id"
    assert id_cite.pincite == "166"
    assert id_cite.authority is tseng.authority
    assert id_cite.proposition.startswith("Congress sought to give passengers")


def test_quote_goes_to_the_citation_that_introduces_it_and_nested_cites_are_marked():
    text = (
        "The court in the case of Varghese v. China Southern Airlines Co., Ltd., 925 F.3d 1339 "
        "(11th Cir. 2019), stating “We agree. The stay tolls the period. "
        "See Zicherman v. Korean Air Lines Co., Ltd., 516 F.3d 1237, 1254 (11th Cir. 2008).” "
        "Plaintiff's claim is timely."
    )
    varghese, zicherman = extract(text).citations
    assert varghese.authority.case_name == "Varghese v. China Southern Airlines Co., Ltd."
    assert varghese.quotes == [
        "We agree. The stay tolls the period. "
        "See Zicherman v. Korean Air Lines Co., Ltd., 516 F.3d 1237, 1254 (11th Cir. 2008)."
    ]
    assert not varghese.in_quotation
    assert zicherman.in_quotation
    assert zicherman.pincite == "1254"
    assert zicherman.quotes == []


def test_in_re_names_keep_their_prefix_and_statutes_are_not_case_citations():
    text = (
        "The stay applies. 11 U.S.C. § 362(a). In re Air Crash Disaster Near New Orleans, La., "
        "821 F.2d 1147, 1165 (5th Cir. 1987)."
    )
    extraction = extract(text)
    (citation,) = extraction.citations
    assert citation.cite_text.startswith("In re Air Crash")
    assert citation.authority.case_name == "In re Air Crash Disaster Near New Orleans, La."
    assert extraction.non_case_citations == 1
