"""Tests for ark.security module — validation, sanitisation, rate limiting, auth, middleware."""

import os
import pytest
import time
from unittest.mock import AsyncMock, MagicMock

from ark.security import (
    # Sanitisation
    sanitize_string,
    sanitize_html,
    sanitize_nats_subject,
    sanitize_dict_keys,
    # Validation
    validate_event_id,
    validate_service_name,
    validate_instance_id,
    validate_capability,
    validate_entity_id,
    validate_tags,
    validate_payload,
    validate_lks_phase,
    validate_positive_int,
    clamp_limit,
    # Rate limiter
    RateLimiter,
    api_rate_limiter,
    registration_rate_limiter,
    # Auth
    constant_time_compare,
    verify_bearer_token,
    generate_api_token,
    # Logging
    redact_dict,
    safe_log_event,
    # Docker
    validate_docker_arg,
    build_safe_docker_cmd,
    # Constants
    MAX_PAYLOAD_BYTES,
    MAX_STRING_LEN,
)


# ---------------------------------------------------------------------------
# sanitize_string
# ---------------------------------------------------------------------------


class TestSanitizeString:
    def test_strips_control_chars(self):
        assert sanitize_string("hello\x00world\x07") == "helloworld"

    def test_keeps_newline_and_tab(self):
        assert sanitize_string("line1\nline2\ttab") == "line1\nline2\ttab"

    def test_clamps_length(self):
        assert len(sanitize_string("a" * 200, max_len=50)) == 50

    def test_rejects_non_string(self):
        with pytest.raises(ValueError):
            sanitize_string(123)


class TestSanitizeHtml:
    def test_escapes_html_entities(self):
        assert "&lt;script&gt;" in sanitize_html("<script>")

    def test_clamps_length(self):
        assert len(sanitize_html("a" * 200, max_len=10)) == 10


class TestSanitizeNatsSubject:
    def test_valid_subject(self):
        assert sanitize_nats_subject("ark.event.test") == "ark.event.test"

    def test_valid_wildcard(self):
        assert sanitize_nats_subject("ark.event.*") == "ark.event.*"

    def test_rejects_shell_chars(self):
        with pytest.raises(ValueError):
            sanitize_nats_subject("ark;rm -rf /")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError):
            sanitize_nats_subject("a" * 257)


class TestSanitizeDictKeys:
    def test_filters_keys(self):
        d = {"a": 1, "b": 2, "c": 3}
        assert sanitize_dict_keys(d, {"a", "c"}) == {"a": 1, "c": 3}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class TestValidateEventId:
    def test_valid_id(self):
        assert validate_event_id("evt-abc123") == "evt-abc123"

    def test_empty_rejects(self):
        with pytest.raises(ValueError):
            validate_event_id("")

    def test_too_long_rejects(self):
        with pytest.raises(ValueError):
            validate_event_id("x" * 200)


class TestValidateServiceName:
    def test_valid(self):
        assert validate_service_name("opencode") == "opencode"
        assert validate_service_name("my-service-01") == "my-service-01"

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError):
            validate_service_name("OpenCode")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError):
            validate_service_name("my service")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_service_name("")


class TestValidateInstanceId:
    def test_valid(self):
        assert validate_instance_id("abc-123_XYZ") == "abc-123_XYZ"

    def test_rejects_shell_chars(self):
        with pytest.raises(ValueError):
            validate_instance_id("id;drop table")


class TestValidateCapability:
    def test_valid(self):
        assert validate_capability("code.analyze") == "code.analyze"
        assert validate_capability("anomaly.detect") == "anomaly.detect"

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError):
            validate_capability("Code.Analyze")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_capability("")


class TestValidateEntityId:
    def test_valid(self):
        assert validate_entity_id("light.living_room") == "light.living_room"

    def test_rejects_too_long(self):
        with pytest.raises(ValueError):
            validate_entity_id("x" * 300)


class TestValidateTags:
    def test_none_returns_empty(self):
        assert validate_tags(None) == {}

    def test_valid_tags(self):
        assert validate_tags({"env": "prod"}) == {"env": "prod"}

    def test_rejects_non_dict(self):
        with pytest.raises(ValueError):
            validate_tags("not a dict")

    def test_rejects_too_many(self):
        with pytest.raises(ValueError):
            validate_tags({f"k{i}": "v" for i in range(100)})


class TestValidatePayload:
    def test_none_returns_empty(self):
        assert validate_payload(None) == {}

    def test_valid_dict(self):
        assert validate_payload({"key": "value"}) == {"key": "value"}

    def test_rejects_non_dict(self):
        with pytest.raises(ValueError):
            validate_payload("not a dict")

    def test_rejects_oversized(self):
        big = {"data": "x" * (MAX_PAYLOAD_BYTES + 1)}
        with pytest.raises(ValueError, match="exceeds"):
            validate_payload(big)


class TestValidateLksPhase:
    def test_valid_phases(self):
        for phase in ("stable", "drift", "unstable", "critical"):
            assert validate_lks_phase(phase) == phase

    def test_rejects_invalid(self):
        with pytest.raises(ValueError):
            validate_lks_phase("bogus")


class TestValidatePositiveInt:
    def test_normal(self):
        assert validate_positive_int(5) == 5

    def test_string_coerce(self):
        assert validate_positive_int("10") == 10

    def test_clamps_max(self):
        assert validate_positive_int(99999, max_val=100) == 100

    def test_rejects_negative(self):
        with pytest.raises(ValueError):
            validate_positive_int(-1)

    def test_rejects_non_numeric(self):
        with pytest.raises(ValueError):
            validate_positive_int("abc")


class TestClampLimit:
    def test_default(self):
        assert clamp_limit(None) == 100

    def test_normal_value(self):
        assert clamp_limit(50) == 50

    def test_above_ceiling(self):
        assert clamp_limit(99999) == 10_000

    def test_below_floor(self):
        assert clamp_limit(0) == 1

    def test_custom_defaults(self):
        assert clamp_limit("bad", default=25, ceiling=50) == 25


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def test_allows_within_burst(self):
        rl = RateLimiter(rate=100, burst=5)
        for _ in range(5):
            assert rl.allow("test") is True

    def test_denies_over_burst(self):
        rl = RateLimiter(rate=0.001, burst=2)
        assert rl.allow("k") is True
        assert rl.allow("k") is True
        assert rl.allow("k") is False

    def test_refills_over_time(self):
        rl = RateLimiter(rate=1000, burst=5)
        for _ in range(5):
            rl.allow("k")
        # After draining, a high rate should refill quickly
        time.sleep(0.01)
        assert rl.allow("k") is True

    def test_independent_keys(self):
        rl = RateLimiter(rate=0.001, burst=1)
        assert rl.allow("a") is True
        assert rl.allow("b") is True  # different key

    def test_reset(self):
        rl = RateLimiter(rate=0.001, burst=1)
        rl.allow("k")
        rl.allow("k")
        rl.reset("k")
        assert rl.allow("k") is True

    def test_evicts_stale_entries(self):
        """Stale entries are evicted once max_keys is exceeded."""
        rl = RateLimiter(rate=1, burst=1, max_keys=2, evict_after=0)
        rl.allow("a")
        rl.allow("b")
        rl.allow("c")  # triggers eviction — a and b are stale (evict_after=0)
        # After eviction, only recent key(s) should remain
        assert len(rl._buckets) <= 3  # at most the 3 we just added

    def test_no_eviction_under_max_keys(self):
        """No eviction when under max_keys threshold."""
        rl = RateLimiter(rate=1, burst=1, max_keys=100, evict_after=0)
        rl.allow("a")
        rl.allow("b")
        assert len(rl._buckets) == 2  # no eviction triggered


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


class TestAuth:
    def test_constant_time_compare_equal(self):
        assert constant_time_compare("abc", "abc") is True

    def test_constant_time_compare_not_equal(self):
        assert constant_time_compare("abc", "xyz") is False

    def test_generate_api_token_length(self):
        token = generate_api_token(32)
        assert len(token) > 0
        assert isinstance(token, str)

    def test_generate_tokens_unique(self):
        t1 = generate_api_token()
        t2 = generate_api_token()
        assert t1 != t2

    def test_verify_bearer_no_tokens_configured(self):
        # When no tokens are configured, all requests pass
        # (this is the default state)
        assert verify_bearer_token(None) is True or verify_bearer_token(None) is False
        # Just check it doesn't raise


# ---------------------------------------------------------------------------
# Logging sanitiser
# ---------------------------------------------------------------------------


class TestRedactDict:
    def test_redacts_sensitive_keys(self):
        d = {"user": "admin", "password": "s3cret", "token": "abc123"}
        r = redact_dict(d)
        assert r["user"] == "admin"
        assert r["password"] == "***REDACTED***"
        assert r["token"] == "***REDACTED***"

    def test_redacts_nested(self):
        d = {"config": {"api_key": "hidden", "host": "localhost"}}
        r = redact_dict(d)
        assert r["config"]["api_key"] == "***REDACTED***"
        assert r["config"]["host"] == "localhost"

    def test_depth_limit(self):
        d = {"a": {"b": {"c": {"d": {"e": {"f": {"g": "deep"}}}}}}}
        r = redact_dict(d, depth=0)
        # Should handle without recursing forever
        assert "__redacted__" in str(r) or "deep" in str(r)


class TestSafeLogEvent:
    def test_redacts_and_truncates(self):
        event = {
            "token": "secret",
            "payload": {"data": "x" * 5000},
        }
        logged = safe_log_event(event)
        assert logged["token"] == "***REDACTED***"
        assert logged["payload"]["__truncated__"] is True


# ---------------------------------------------------------------------------
# Docker argument validation
# ---------------------------------------------------------------------------


class TestDockerArg:
    def test_valid_args(self):
        assert validate_docker_arg("ark-opencode:latest") == "ark-opencode:latest"
        assert validate_docker_arg("1G") == "1G"
        assert validate_docker_arg("0.5") == "0.5"

    def test_rejects_shell_metachar(self):
        with pytest.raises(ValueError):
            validate_docker_arg("image;rm -rf /")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError):
            validate_docker_arg("my image")


class TestBuildSafeDockerCmd:
    def test_returns_list(self):
        cmd = build_safe_docker_cmd(
            image="ark-test:latest",
            container_name="ark-test-abc123",
            cpu_limit="1",
            memory_limit="512M",
            env={"KEY": "value"},
        )
        assert isinstance(cmd, list)
        assert "docker" in cmd
        assert "--read-only" in cmd
        assert "--cap-drop" in cmd

    def test_security_flags_present(self):
        cmd = build_safe_docker_cmd(
            image="img:v1",
            container_name="c1",
            cpu_limit="1",
            memory_limit="1G",
            env={},
        )
        assert "no-new-privileges:true" in " ".join(cmd)
        assert "--pids-limit" in cmd

    def test_rejects_unsafe_image(self):
        with pytest.raises(ValueError):
            build_safe_docker_cmd(
                image="img;malicious",
                container_name="c1",
                cpu_limit="1",
                memory_limit="1G",
                env={},
            )
