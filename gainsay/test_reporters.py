import pytest

from gainsay.reporters import invented_series


@pytest.mark.parametrize("reporter", ["F.6th", "F.5th", "N.E.4th", "S.W.4th", "F. Supp. 5th", "Cal. Rptr. 4th"])
def test_series_past_the_newest_are_invented(reporter):
    assert invented_series(reporter).startswith(f"there is no {reporter}")


@pytest.mark.parametrize("reporter", ["F.4th", "F.3d", "N.E.3d", "F. Supp. 3d", "L. Ed. 2d", "Xyz.9th", "U.S.C. 2d"])
def test_real_or_unrecognised_reporters_are_not_flagged(reporter):
    assert invented_series(reporter) is None
