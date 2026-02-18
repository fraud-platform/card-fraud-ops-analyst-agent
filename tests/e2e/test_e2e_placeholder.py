"""Minimal e2e marker test placeholder.

This test intentionally validates marker wiring and repository test structure.
Cross-repo e2e flows run in dedicated platform/e2e repositories.
"""

import pytest


@pytest.mark.e2e
def test_e2e_marker_wiring() -> None:
    assert True
