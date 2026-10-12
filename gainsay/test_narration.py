from gainsay.findings import FAIL, NOT_APPLICABLE, PASS, UNVERIFIABLE, Finding
from gainsay.narration import citation_label, narrate


def findings(**outcomes):
    return [Finding(check, outcome, "") for check, outcome in outcomes.items()]


def test_not_found_citation_reads_as_one_sentence_with_whats_next():
    sentence = narrate(
        "Varghese, 925 F.3d 1339",
        findings(existence=FAIL, identity=UNVERIFIABLE, quotation=UNVERIFIABLE,
                 proposition=UNVERIFIABLE, pincite=NOT_APPLICABLE),
        "Kaiser Steel Corp., 391 U.S. 593",
    )
    assert sentence == (
        "Varghese, 925 F.3d 1339: not found after the lookup and a name search → support couldn't be judged "
        "→ Not found in searched sources. Next: Kaiser Steel Corp., 391 U.S. 593."
    )


def test_real_case_misused_names_each_step():
    sentence = narrate(
        "Kaiser Steel Corp., 391 U.S. 593",
        findings(existence=PASS, identity=PASS, quotation=NOT_APPLICABLE, proposition=FAIL, pincite=FAIL),
        None,
    )
    assert sentence == (
        "Kaiser Steel Corp., 391 U.S. 593: found → opinion doesn't support the statement "
        "→ pincite past the opinion's pages → Doesn't support the proposition. That was the last citation."
    )


def test_labels_use_the_first_party_and_reporter_cite():
    assert citation_label("Varghese v. China Southern Airlines Co., Ltd.", "925 F.3d 1339", "x") == (
        "Varghese, 925 F.3d 1339"
    )
    assert citation_label(None, None, "Id. at 166, 119 S. Ct. 662 (1999)") == "Unresolved citation, Id. at 166, 119 S. Ct. 662"
