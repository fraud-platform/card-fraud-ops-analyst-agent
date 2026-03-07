"""Tests for type_utils module."""

from decimal import Decimal

from app.utils.type_utils import to_float


class TestToFloat:
    """Test the to_float type conversion utility."""

    def test_float_passthrough(self):
        """Float values should pass through unchanged."""
        assert to_float(3.14) == 3.14
        assert to_float(0.0) == 0.0
        assert to_float(-1.5) == -1.5

    def test_int_conversion(self):
        """Int values should be converted to float."""
        assert to_float(42) == 42.0
        assert to_float(0) == 0.0
        assert to_float(-10) == -10.0

    def test_decimal_conversion(self):
        """Decimal values should be converted to float."""
        assert to_float(Decimal("3.14159")) == 3.14159
        assert to_float(Decimal("0.0")) == 0.0
        assert to_float(Decimal("-2.5")) == -2.5

    def test_string_conversion(self):
        """String values that represent numbers should be converted."""
        assert to_float("3.14") == 3.14
        assert to_float("42") == 42.0
        assert to_float("-1.5") == -1.5

    def test_invalid_string_returns_default(self):
        """Non-numeric strings should return the default value."""
        assert to_float("invalid") == 0.0
        assert to_float("abc123") == 0.0
        assert to_float("") == 0.0

    def test_custom_default(self):
        """Custom default values should be used for invalid conversions."""
        assert to_float("invalid", -1.0) == -1.0
        assert to_float(None, 99.0) == 99.0
        assert to_float([], 5.0) == 5.0

    def test_none_returns_default(self):
        """None should return the default value."""
        assert to_float(None) == 0.0
        assert to_float(None, -1.0) == -1.0

    def test_list_returns_default(self):
        """Lists should return the default value."""
        assert to_float([1, 2, 3]) == 0.0
        assert to_float([], 5.0) == 5.0

    def test_dict_returns_default(self):
        """Dicts should return the default value."""
        assert to_float({"key": "value"}) == 0.0
        assert to_float({}, -1.0) == -1.0
