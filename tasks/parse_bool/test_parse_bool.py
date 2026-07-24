import pytest
from parse_bool import parse_bool
def test_yes(): assert parse_bool("Yes") is True
def test_no_spaces(): assert parse_bool(" no ") is False
def test_one(): assert parse_bool("1") is True
def test_off(): assert parse_bool("OFF") is False
def test_unknown():
    with pytest.raises(ValueError):
        parse_bool("maybe")
