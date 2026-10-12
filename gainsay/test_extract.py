from gainsay.extract import clean_text, extract, find_quotes, sentence_spans

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


def test_nested_single_quote_goes_to_the_citation_after_it_even_without_a_closing_mark():
    text = (
        "The court stated, “Congress enacted the Convention to 'modernize and unify the Warsaw system. "
        "“El Al Israel Airlines, Ltd. v. Tseng, 525 U.S. 155, 161 (1999). It is plaintiff's right.” "
        "Varghese v. China Southern Airlines Co., Ltd., 925 F.3d 1339 (11th Cir. 2019)."
    )
    tseng, varghese = extract(text).citations
    assert tseng.quotes == ["modernize and unify the Warsaw system."]
    assert tseng.in_quotation


def test_apostrophes_are_not_nested_quotes():
    text = (
        "The court stated, “The carrier's duty and the passengers’ claims survive the stay.” "
        "Zicherman v. Korean Air Lines Co., Ltd., 516 F.3d 1237, 1254 (11th Cir. 2008)."
    )
    (zicherman,) = extract(text).citations
    assert zicherman.quotes == ["The carrier's duty and the passengers’ claims survive the stay."]


def test_table_of_authorities_entries_are_skipped():
    text = (
        "TABLE OF AUTHORITIES Chambers v. NASCO, Inc., 501 U.S. 32 (1991) ............................ 13, 14 "
        "ARGUMENT Courts have inherent power to sanction bad faith. Chambers v. NASCO, Inc., 501 U.S. 32, 46 (1991)."
    )
    extraction = extract(text)
    (citation,) = extraction.citations
    assert citation.pincite == "46"
    assert extraction.table_entries == 1


def test_subsequent_history_takes_the_case_name():
    text = (
        "Counsel who play a minor role are not sanctioned. De La Fuente v. DCI Telecomms., Inc., "
        "269 F. Supp. 2d 229, 235 (S.D.N.Y.), aff'd and remanded, 82 F. App'x 723 (2d Cir. 2003)."
    )
    district, appeal = extract(text).citations
    assert appeal.authority.case_name == district.authority.case_name == "De La Fuente v. DCI Telecomms., Inc."
    assert appeal.authority.reporter_cites == ["82 F. App'x 723"]


def test_id_after_a_record_cite_is_not_a_case_citation():
    text = (
        "Sanctions require bad faith. Rankin v. City of Niagara Falls, 293 F.R.D. 375, 390 (W.D.N.Y. 2013). "
        "Bad faith must be shown clearly. Id. at 391. "
        "He did not know the tool could invent cases. Schwartz Decl. ¶ 15. He regrets it. Id. at ¶ 29. "
        "He acted in good faith. Id. at ¶ 30."
    )
    extraction = extract(text)
    assert [(c.kind, c.pincite) for c in extraction.citations] == [("full", "390"), ("id", "391")]
    assert extraction.record_references == 2


def test_docket_numbers_leave_the_case_name():
    text = "The court declined. Rivas v. Bowling Green Assocs., L.P., No. 13-CV-7812 PKC, 2014 WL 3694983 (S.D.N.Y. 2014)."
    (citation,) = extract(text).citations
    assert citation.authority.case_name == "Rivas v. Bowling Green Assocs., L.P."


def test_docket_numbers_are_kept_on_the_case_and_history_is_marked():
    text = (
        "Sanctions need bad faith. Rivas v. Bowling Green Assocs., L.P., No. 13-CV-7812 PKC, "
        "2014 WL 3694983, at *1 (S.D.N.Y. July 24, 2014). The standard is high. Rankin v. City of Niagara Falls, "
        "293 F.R.D. 375, 390 (W.D.N.Y. 2013), aff'd, 569 F. App'x 25 (2d Cir. 2014)."
    )
    rivas, rankin, affirmance = extract(text).citations
    assert rivas.authority.docket_number == "13-cv-07812"
    assert (rankin.kind, affirmance.kind) == ("full", "history")
    assert affirmance.authority.case_name == "Rankin v. City of Niagara Falls"


def test_footnote_cross_references_are_not_case_citations():
    text = "As discussed supra at n. 4, counsel acted in good faith. Chambers v. NASCO, Inc., 501 U.S. 32, 46 (1991)."
    extraction = extract(text)
    assert [c.kind for c in extraction.citations] == ["full"]
    assert extraction.record_references == 1


def test_citations_to_reporter_series_that_dont_exist_are_found():
    text = (
        "Courts agree the stay tolls the period. See Smith v. Jones Corp., 475 F.6th 972, 1010 (8th Cir. 1983). "
        "The rule applies. In re Estate of Doe v. Bank of America, 936 F. Supp. 5th 413 (9th Cir. 2008). "
        "The rule is settled. Kaiser Steel Corp. v. W.S. Ranch Co., 391 U.S. 593, 594 (1968)."
    )
    smith, doe, kaiser = extract(text).citations
    assert (smith.authority.case_name, smith.authority.reporter_cites, smith.pincite) == (
        "Smith v. Jones Corp.", ["475 F.6th 972"], "1010"
    )
    assert smith.authority.invented_reporter == "there is no F.6th: the newest series of that reporter is F.4th"
    assert smith.proposition == "Courts agree the stay tolls the period."
    assert doe.authority.case_name == "In re Estate of Doe v. Bank of America"
    assert kaiser.authority.invented_reporter is None


def test_italic_asterisks_and_case_number_prefixes_leave_names():
    text = (
        "See *Wyoming v. USDA*, 661 F.3d 1209, 1230 (10th Cir. 2011); *In re Dimare*, Ca. No. 08-10598, "
        "Adv. Pro. 08-1234, 462 B.R. 283 (Bankr. D. Mass. 2011); Rivas, 2014 WL 3694983, at *1."
    )
    names = [c.authority.case_name for c in extract(text).citations if c.authority]
    assert names[:2] == ["Wyoming v. USDA", "In re Dimare"]
    assert "at *1" in clean_text(text)


def test_headings_end_where_their_line_ends():
    text = (
        "These actions are inconsistent with evidence of bad faith behavior.\n"
        "A. Mr. Schwartz’s Misunderstanding of ChatGPT Does Not Show Bad Faith\n"
        "For sanctions to issue, the Court must find knowing conduct. In re Pennie & Edmonds LLP,\n"
        "323 F.3d 86, 87 (2d Cir. 2003).\n"
        "II. SANCTIONS ARE NOT WARRANTED BECAUSE RESPONDENTS\n"
        "ACTIONS WERE NOT IN BAD FAITH\n"
        "Bad faith requires more than a mistake. Id. at 90."
    )
    pennie, id_cite = extract(text).citations
    assert pennie.proposition == "For sanctions to issue, the Court must find knowing conduct."
    assert id_cite.proposition == "Bad faith requires more than a mistake."


def test_a_wrapped_body_line_is_not_a_heading():
    text = (
        "The firm relied on the research of\n"
        "A. Smith and others who found nothing amiss in the citations. See In re Pennie & Edmonds\n"
        "LLP, 323 F.3d 86, 87 (2d Cir. 2003)."
    )
    (citation,) = extract(text).citations
    assert citation.proposition.startswith("The firm relied on the research of A. Smith")


def test_an_exhibit_letter_ends_its_sentence():
    text = (
        "ChatGPT was widely hailed in the press. See Alger Decl., Ex. A. Much less was being "
        "written about its deep flaws. Id. at Ex. C. Courts weigh the state of knowledge at the time. "
        "In re Pennie & Edmonds LLP, 323 F.3d 86, 87 (2d Cir. 2003)."
    )
    (citation,) = extract(text).citations
    assert citation.proposition == "Courts weigh the state of knowledge at the time."
    cleaned = clean_text(text)
    sentences = [cleaned[a:b].strip() for a, b in sentence_spans(cleaned, [])]
    assert "Much less was being written about its deep flaws." in sentences


def test_numbered_affidavit_paragraphs_are_not_headings():
    text = (
        "4. That the opinion in Miller v. United Airlines, Inc., 174 F.3d 366 (2d Cir. 1999) is incomplete.\n"
        "5. That the opinion in Shaboon v. Egyptair 2013 IL App (1st) 111279-U (Ill. App. Ct. 2013)\n"
        "is an unpublished opinion."
    )
    miller, shaboon = extract(text).citations
    assert shaboon.proposition == (
        "That the opinion in Shaboon v. Egyptair 2013 IL App (1st) 111279-U (Ill. App. Ct. 2013) "
        "is an unpublished opinion."
    )


def test_a_name_eyecite_cuts_at_an_ampersand_is_recovered_whole():
    text = (
        "Whether confusion is likely must be considered in context.\n"
        "*See G. D. Searle & Co. v. Charles Pfizer & Co.*, 265 F.2d 385, 388 (7th Cir. 1959)."
    )
    (citation,) = extract(text).citations
    assert citation.authority.case_name == "G. D. Searle & Co. v. Charles Pfizer & Co."
    assert citation.cite_text.startswith("G. D. Searle & Co.")


def test_a_name_starts_after_a_closing_parenthetical_or_an_id():
    simon = extract(
        "”Id. (reassigning case from Hughes, J.). In Simon v. City of Clute, 825 F.2d 940 (5th Cir. 1987), "
        "for example, the district court erred."
    ).citations[-1]
    assert simon.authority.case_name == "Simon v. City of Clute"
    conoshenti = extract(
        "the decision was causally related to taking leave. *Id.* *Conoshenti v. Public Service Electric & Gas "
        "Company*, 364 F.3d 135, 146-47 (3d Cir. 2004)."
    ).citations[-1]
    assert conoshenti.authority.case_name == "Conoshenti v. Public Service Electric & Gas Company"


def test_a_name_walked_back_stops_at_its_signal():
    text = (
        "the court erred by not reading the claims most favorably to Evolutionary. See Content Extraction & "
        "Transmission LLC v. Wells Fargo Bank, Nat. Ass’n, 776 F.3d 1343, 1347 (Fed. Cir. 2014)."
    )
    (citation,) = extract(text).citations
    assert citation.authority.case_name == "Content Extraction & Transmission LLC v. Wells Fargo Bank, Nat. Ass’n"


def test_california_style_names_come_before_the_court_and_year():
    text = (
        "The court must follow it. (Columbia Steel Casting Co. v. Portland GE (9th Cir. 1996) "
        "111 F.3d 1427, 1443.) The rule applies here."
    )
    (citation,) = extract(text).citations
    assert citation.authority.case_name == "Columbia Steel Casting Co. v. Portland GE"
    assert citation.authority.reporter_cites == ["111 F.3d 1427"]


def test_a_short_form_name_starts_after_the_sentence_before_it():
    text = (
        "Weaver v. FMCSA, 744 F.3d 142, 145 (D.C. Cir. 2014). The agency keeps the records in MCMIS.\n"
        "Weaver, 744 F.3d at 143. It disclosed them."
    )
    full, short = extract(text).citations
    assert short.cite_text.startswith("Weaver, 744 F.3d at 143")


def test_a_footnote_number_after_a_period_still_ends_the_sentence():
    text = (
        "Treaties are the supreme law of the land. See U.S. Const. art. VI, cl. 2; El Al Israel Airlines, Ltd. "
        "v. Tseng, 525 U.S. 155 (1999).2 Pursuant to Article 29, the Convention preempts all claims."
    )
    (tseng,) = extract(text).citations
    assert tseng.proposition == "Treaties are the supreme law of the land."


def test_a_spaced_right_quote_still_closes_the_quotation():
    text = (
        "there is no “evidentiary presumption of fair use for all private uses. ” Sony BMG Music Entm’t v. "
        "Tenenbaum, 672 F. Supp. 2d 217, 226 (D. Mass. 2009). The court agreed."
    )
    (span,) = find_quotes(text)
    assert text[span[0]:span[1]] == "evidentiary presumption of fair use for all private uses. "


def test_signals_and_explanatory_parentheticals_are_kept_with_each_citation():
    text = (
        "Congress meant to limit the statute. CTS Corp. v. Waldburger, 134 S. Ct. 2175, 2185 (2014) "
        "(rejecting a reading that would expand the statute); see also Smith v. Jones, 1 F.3d 2, 5 "
        "(2d Cir. 1990) (quoting Doe v. Roe, 2 F.3d 3 (2d Cir. 1991)); cf. Foo v. Bar, 3 F.3d 4 (2d Cir. 1992) "
        "(citation omitted). But see Baz v. Qux, 4 F.3d 5, 9 (2d Cir. 1993) (holding that the statute "
        "reaches (a) private parties and (b) states)."
    )
    cts, smith, doe, foo, baz = extract(text).citations
    assert (cts.signal, cts.parenthetical) == (None, "rejecting a reading that would expand the statute")
    assert (smith.signal, smith.parenthetical) == ("see also", None)
    assert (foo.signal, foo.parenthetical) == ("cf.", None)
    assert baz.signal == "but see"
    assert baz.parenthetical == "holding that the statute reaches (a) private parties and (b) states"


def test_who_wrote_an_opinion_is_not_what_it_holds():
    text = (
        "The standard is strict. Olmstead v. United States, 277 U.S. 438, 478 (1928) (Brandeis, J., dissenting). "
        "It applies here. Int’l Internship Program v. Napolitano, 718 F. Supp. 2d 1, 5 (D.D.C. 2010) (Leon, J.)."
    )
    olmstead, internship = extract(text).citations
    assert olmstead.parenthetical is None and internship.parenthetical is None


def test_an_id_after_a_statute_refers_to_the_statute():
    text = (
        "Retaliation is barred. Maggio v. Fla. Dep’t of Labor, 899 So. 2d 1074, 1079 (Fla. 2005). "
        "Review is for cause under 5 U.S.C. § 7521. Id. 7521(a)."
    )
    citations = extract(text).citations
    assert [c.kind for c in citations] == ["full"]


def test_an_id_at_a_page_still_refers_to_the_case_after_a_statute_in_prose():
    text = (
        "Rivas v. Bowling Green Assocs., L.P., No. 13 Civ. 7812, 2014 WL 3694983, at *1 (S.D.N.Y. July 24, 2014). "
        "The attorneys knew 28 U.S.C. § 1441(b)(2) barred removal. Id. at *2."
    )
    rivas, id_cite = extract(text).citations
    assert id_cite.kind == "id" and id_cite.authority is rivas.authority


def test_an_id_pinned_to_a_section_is_a_statute():
    text = (
        "Retaliation is barred. Maggio v. Fla. Dep’t of Labor, 899 So. 2d 1074, 1079 (Fla. 2005). "
        "The statute forbids it. Id. 448.102(3). Removal requires cause. Id. 7521(a)."
    )
    assert [c.kind for c in extract(text).citations] == ["full"]


def test_prose_and_record_cites_before_a_name_are_dropped():
    kola = extract("Unlike KOLA, Inc. v. United States, 882 F.2d 361 (9th Cir. 1989), the agency acted.").citations[0]
    assert kola.authority.case_name == "KOLA, Inc. v. United States"
    sierra = extract("See Respondent Brief 24-28, Sierra Club v. EPA, 479 F.3d 875 (D.C. Cir. 2007).").citations[0]
    assert sierra.authority.case_name == "Sierra Club v. EPA"


def test_an_ecf_stamp_inside_a_citation_is_removed():
    text = (
        "The employer required an illegal act. Sabine Pilot Serv., Inc. v. Hauck, - 1 -Case 1:23-cv-00281-MAC "
        "Document 41 Filed 10/02/24 Page 2 of 6 PageID #: 315 687 S.W.2d 733, 735 (Tex. 1985). The rule is narrow."
    )
    (citation,) = extract(text).citations
    assert citation.authority.case_name == "Sabine Pilot Serv., Inc. v. Hauck"
    assert "Document 41" not in citation.cite_text


def test_a_dashed_page_number_at_a_line_end_is_removed():
    text = (
        "The employer required an illegal act. Sabine Pilot Serv., Inc. v. Hauck, - 1 -\n"
        "Case 1:23-cv-00281-MAC Document 41 Filed 10/02/24 Page 2 of 6 PageID #: 315\n"
        "687 S.W.2d 733, 735 (Tex. 1985). The rule is narrow."
    )
    (citation,) = extract(text).citations
    assert citation.authority.case_name == "Sabine Pilot Serv., Inc. v. Hauck"
