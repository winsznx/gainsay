import pytest

from gainsay.jurisdiction import court_system_fits


@pytest.mark.parametrize(
    ("cites", "court_id", "fits"),
    [
        (["360 N.J. Super. 360"], "ca2", False),
        (["360 N.J. Super. 360"], "njsuperctappdiv", True),
        (["905 F. Supp. 2d 121"], "dcd", True),
        (["905 F. Supp. 2d 121"], "texapp", False),
        (["2013 IL App (1st) 111279-U"], "illappct", True),
        (["2019 WL 4639462"], "texapp", True),
        (["2019 WL 4639462"], "ca5", True),
        (["360 N.J. Super. 360"], None, True),
        (["360 N.J. Super. 360"], "not-a-court", True),
    ],
)
def test_court_system_fits(cites, court_id, fits):
    assert court_system_fits(cites, court_id) is fits
