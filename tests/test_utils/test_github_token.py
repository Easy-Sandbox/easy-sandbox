"""Tests for the shared GitHub-token guidance (task 206).

The module is the single source of truth for the rate-limit message and the
officially verified fine-grained PAT prefill URL used by both clients
(``utils.registry`` / ``utils.template_index``) and by the CLI onboarding.
"""

from __future__ import annotations

from easy_sandbox.utils.github_token import (
    FINE_GRAINED_PAT_URL,
    GITHUB_TOKEN_CONFIG_KEY,
    GITHUB_TOKEN_ENV_VAR,
    rate_limit_message,
    rate_limit_suggestion,
)


class TestConstants:
    def test_env_var_and_config_key(self) -> None:
        assert GITHUB_TOKEN_ENV_VAR == "GITHUB_TOKEN"
        assert GITHUB_TOKEN_CONFIG_KEY == "github_token"

    def test_pat_url_is_the_official_prefill_endpoint(self) -> None:
        assert FINE_GRAINED_PAT_URL.startswith(
            "https://github.com/settings/personal-access-tokens/new?"
        )
        # Officially supported URL parameters (see GitHub docs).
        assert "expires_in=90" in FINE_GRAINED_PAT_URL
        assert "contents=read" in FINE_GRAINED_PAT_URL

    def test_pat_url_requests_no_write_or_admin_scope(self) -> None:
        assert "=write" not in FINE_GRAINED_PAT_URL
        assert "=admin" not in FINE_GRAINED_PAT_URL


class TestRateLimitMessage:
    def test_mentions_the_anonymous_hourly_budget(self) -> None:
        message = rate_limit_message()
        assert "rate limit" in message.lower()
        assert "60/hour" in message

    def test_operation_is_embedded(self) -> None:
        message = rate_limit_message(operation="fetching the template index")
        assert "while fetching the template index" in message

    def test_base_message_has_no_dangling_while(self) -> None:
        assert "while" not in rate_limit_message()


class TestRateLimitSuggestion:
    def test_recommends_config_set_over_token_flag(self) -> None:
        suggestion = rate_limit_suggestion()
        assert "ebx config set github_token" in suggestion
        assert "~/.ebx/.env" in suggestion

    def test_token_flag_documented_as_leak_prone(self) -> None:
        suggestion = rate_limit_suggestion()
        after_flag = suggestion.split("'--token <value>'", 1)
        assert len(after_flag) == 2, "the --token fallback must still be documented"
        assert "may leak into shell history and process listings" in after_flag[1]

    def test_contains_verified_url_and_setup_guidance(self) -> None:
        suggestion = rate_limit_suggestion()
        assert FINE_GRAINED_PAT_URL in suggestion
        assert "public repositories need no extra permissions" in suggestion
        assert "90-day expiry is recommended" in suggestion

    def test_covers_ci_secret_injection(self) -> None:
        suggestion = rate_limit_suggestion()
        assert "GITHUB_TOKEN" in suggestion
        assert "secret" in suggestion.lower()

    def test_extra_sentence_is_appended_last(self) -> None:
        suggestion = rate_limit_suggestion(extra="Mirror hint.")
        assert suggestion.endswith("Mirror hint.")
