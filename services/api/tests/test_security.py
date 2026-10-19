import pytest

from services.api.app.security import normalize_phone


def test_chinese_phone_is_normalized_to_e164():
    assert normalize_phone("138 0013 8000") == "+8613800138000"


def test_international_prefix_is_supported():
    assert normalize_phone("0086 13800138000") == "+8613800138000"


def test_invalid_phone_is_rejected():
    with pytest.raises(ValueError):
        normalize_phone("123")
