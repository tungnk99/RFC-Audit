"""Kiểm thử hồi quy cho `candidate_patterns` và `diagnose` đa họ / đa thư viện TLS."""

from __future__ import annotations

import re

from rfcv.domains.rfc_protocol.diagnosis import candidate_patterns


def test_candidate_patterns_prioritizes_observed_and_matches_cross_library_macros() -> None:
    patterns = candidate_patterns("record_overflow", ("illegal_parameter", "none"))
    assert len(patterns) == 2
    # Cảnh báo sai quan sát được phải đứng trước mã kỳ vọng.
    assert re.search(patterns[0], "SSLfatal(s, SSL_AD_ILLEGAL_PARAMETER, ERR_R_INTERNAL_ERROR);")
    assert re.search(patterns[0], "SendAlert(ssl, alert_fatal, illegal_parameter);")
    assert re.search(patterns[1], "SSLfatal(s, SSL_AD_RECORD_OVERFLOW, SSL_R_DATA_LENGTH_TOO_LONG);")
    assert re.search(patterns[1], "GNUTLS_A_RECORD_OVERFLOW")
    assert not re.search(patterns[0], "SendAlert(ssl, alert_fatal, decode_error);")


def test_candidate_patterns_deduplicates_and_skips_none() -> None:
    patterns = candidate_patterns("unexpected_message", ("none", "unexpected_message"))
    assert len(patterns) == 1
    assert re.search(patterns[0], "MBEDTLS_SSL_ALERT_MSG_UNEXPECTED_MESSAGE")
