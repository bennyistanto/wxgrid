"""Coordinate cells in the East Java PU sheets (F65)."""
import math

from wxgrid.readers.jatim_grid import _coord


def test_degree_minute_text():
    lat, how = _coord("07.26,591", -1, 0.5, 12)
    assert math.isclose(lat, -(7 + 26.591 / 60)) and how == "sheet DD.MM,mmm"


def test_decimal_degrees_number_and_text():
    assert _coord(-7.1602, -1, 0.5, 12)[0] == -7.1602          # Pamekasan numeric cell
    assert _coord(113.5764, 1, 90, 145)[0] == 113.5764
    assert _coord("112.68", 1, 90, 145)[0] == 112.68             # Botokan: 68 cannot be minutes
    assert _coord("07.49", -1, 0.5, 12)[0] == -7.49


def test_placeholders_rejected():
    for v in (0.0, 23, "", "abc"):
        assert math.isnan(_coord(v, -1, 0.5, 12)[0])
