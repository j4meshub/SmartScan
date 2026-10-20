from __future__ import annotations

import base64
from collections import Counter

import httpx
import pytest
from pydantic import ValidationError

from services.api.app.config import Settings
from services.api.app.wecom import (
    DisabledWeComAdapter,
    MockWeComAdapter,
    WeComAdapterError,
    WeComConfigurationError,
    WeComHttpAdapter,
    WeComIdentity,
    WeComProviderError,
    create_wecom_adapter,
    decide_wecom_account_action,
)


def live_adapter(handler) -> WeComHttpAdapter:
    client = httpx.Client(
        base_url="https://qyapi.weixin.qq.com",
        transport=httpx.MockTransport(handler),
    )
    return WeComHttpAdapter(
        corp_id="corp-test",
        agent_id="agent-test",
        secret="secret-test",
        client=client,
    )


def test_mock_adapter_marks_evidence_and_missing_phone() -> None:
    adapter = MockWeComAdapter(
        {
            "with-phone": WeComIdentity(
                corp_id="corp-test",
                user_id="member-1",
                phone_e164="+8613800138000",
                assurance="mock",
            ),
            "without-phone": WeComIdentity(
                corp_id="corp-test",
                user_id="member-2",
                phone_e164=None,
                assurance="mock",
            ),
        }
    )

    identity = adapter.resolve("with-phone")
    assert identity.provider_subject == "corp-test:member-1"
    assert identity.assurance == "mock"
    assert not identity.requires_phone_binding
    assert adapter.resolve("without-phone").requires_phone_binding

    with pytest.raises(WeComProviderError, match="wecom_invalid_oauth_code"):
        adapter.resolve("unknown")


def test_mock_adapter_rejects_false_live_assurance() -> None:
    adapter = MockWeComAdapter(
        {
            "bad": WeComIdentity(
                corp_id="corp-test",
                user_id="member-1",
                phone_e164=None,
                assurance="wecom_directory",
            )
        }
    )
    with pytest.raises(WeComConfigurationError, match="wecom_mock_assurance_required"):
        adapter.resolve("bad")


def test_account_decision_contract_covers_binding_and_conflicts() -> None:
    identity = WeComIdentity(
        corp_id="corp-test",
        user_id="member-1",
        phone_e164="+8613800138000",
        assurance="mock",
    )

    bound = decide_wecom_account_action(
        identity,
        bound_identity_user_id="bound-user",
        phone_candidate_user_ids=["different-phone-user"],
    )
    assert bound.action == "use_bound_identity"
    assert bound.canonical_user_id == "bound-user"

    unique = decide_wecom_account_action(
        identity,
        bound_identity_user_id=None,
        phone_candidate_user_ids=["phone-user"],
    )
    assert unique.action == "bind_verified_phone"
    assert unique.canonical_user_id == "phone-user"

    new_user = decide_wecom_account_action(
        identity, bound_identity_user_id=None, phone_candidate_user_ids=[]
    )
    assert new_user.action == "create_wecom_user"

    conflict = decide_wecom_account_action(
        identity,
        bound_identity_user_id=None,
        phone_candidate_user_ids=["candidate-1", "candidate-2"],
    )
    assert conflict.action == "require_conflict_review"

    without_phone = WeComIdentity(
        corp_id="corp-test", user_id="member-2", phone_e164=None, assurance="mock"
    )
    binding = decide_wecom_account_action(
        without_phone,
        bound_identity_user_id=None,
        phone_candidate_user_ids=["must-not-be-guessed"],
    )
    assert binding.action == "require_phone_binding"


def test_live_adapter_resolves_trusted_member_and_reuses_token() -> None:
    calls: Counter[str] = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        calls[request.url.path] += 1
        assert request.url.scheme == "https"
        assert request.url.host == "qyapi.weixin.qq.com"
        if request.url.path == "/cgi-bin/gettoken":
            assert request.url.params["corpid"] == "corp-test"
            assert request.url.params["corpsecret"] == "secret-test"
            return httpx.Response(
                200, json={"errcode": 0, "access_token": "token-test", "expires_in": 7200}
            )
        if request.url.path == "/cgi-bin/auth/getuserinfo":
            assert request.url.params["access_token"] == "token-test"
            assert request.url.params["code"] in {"oauth-code-1", "oauth-code-2"}
            return httpx.Response(200, json={"errcode": 0, "UserId": "member-1"})
        if request.url.path == "/cgi-bin/user/get":
            assert request.url.params["userid"] == "member-1"
            return httpx.Response(
                200,
                json={"errcode": 0, "userid": "member-1", "mobile": "138 0013 8000"},
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    adapter = live_adapter(handler)
    first = adapter.resolve("oauth-code-1")
    second = adapter.resolve("oauth-code-2")

    assert first == second
    assert first.phone_e164 == "+8613800138000"
    assert first.assurance == "wecom_directory"
    assert not first.requires_phone_binding
    assert calls["/cgi-bin/gettoken"] == 1
    assert calls["/cgi-bin/auth/getuserinfo"] == 2
    assert calls["/cgi-bin/user/get"] == 2


def test_live_adapter_keeps_member_without_phone_for_binding() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        responses = {
            "/cgi-bin/gettoken": {"errcode": 0, "access_token": "token-test"},
            "/cgi-bin/auth/getuserinfo": {"errcode": 0, "userid": "member-2"},
            "/cgi-bin/user/get": {"errcode": 0, "userid": "member-2"},
        }
        return httpx.Response(200, json=responses[request.url.path])

    identity = live_adapter(handler).resolve("oauth-code")
    assert identity.user_id == "member-2"
    assert identity.phone_e164 is None
    assert identity.requires_phone_binding


@pytest.mark.parametrize(
    ("auth_payload", "expected_code"),
    [
        ({"errcode": 0, "OpenId": "external-user"}, "wecom_non_member_identity"),
        ({"errcode": 0}, "wecom_identity_missing"),
    ],
)
def test_live_adapter_rejects_non_member_or_missing_identity(
    auth_payload: dict[str, object], expected_code: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/gettoken":
            return httpx.Response(200, json={"errcode": 0, "access_token": "token-test"})
        return httpx.Response(200, json=auth_payload)

    with pytest.raises(WeComProviderError, match=expected_code):
        live_adapter(handler).resolve("oauth-code")


@pytest.mark.parametrize(
    ("member_payload", "expected_code"),
    [
        ({"errcode": 0, "userid": "another-member"}, "wecom_member_mismatch"),
        (
            {"errcode": 0, "userid": "member-1", "mobile": "123"},
            "wecom_invalid_member_phone",
        ),
    ],
)
def test_live_adapter_rejects_untrusted_member_data(
    member_payload: dict[str, object], expected_code: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/gettoken":
            return httpx.Response(200, json={"errcode": 0, "access_token": "token-test"})
        if request.url.path == "/cgi-bin/auth/getuserinfo":
            return httpx.Response(200, json={"errcode": 0, "UserId": "member-1"})
        return httpx.Response(200, json=member_payload)

    with pytest.raises(WeComProviderError, match=expected_code):
        live_adapter(handler).resolve("oauth-code")


def test_provider_errors_are_sanitized_and_redirects_are_not_followed() -> None:
    sensitive_code = "oauth-code-sensitive"
    sensitive_secret = "secret-test"

    def api_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "errcode": 40014,
                "errmsg": f"invalid {sensitive_code} {sensitive_secret}",
            },
        )

    with pytest.raises(WeComProviderError) as api_exc:
        live_adapter(api_error).resolve(sensitive_code)
    assert api_exc.value.code == "wecom_api_error"
    assert sensitive_code not in str(api_exc.value)
    assert sensitive_secret not in str(api_exc.value)

    def redirect(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.invalid/steal"})

    with pytest.raises(WeComProviderError, match="wecom_provider_unavailable"):
        live_adapter(redirect).resolve("oauth-code")


def test_factory_defaults_to_disabled_and_forbids_mock_outside_development() -> None:
    disabled = create_wecom_adapter(Settings(_env_file=None, wecom_mode="disabled"))
    assert isinstance(disabled, DisabledWeComAdapter)
    with pytest.raises(WeComAdapterError, match="wecom_disabled"):
        disabled.resolve("unused")

    settings = Settings(_env_file=None, env="production", wecom_mode="mock")
    with pytest.raises(WeComConfigurationError, match="wecom_mock_development_only"):
        create_wecom_adapter(settings)


def test_live_adapter_requires_complete_configuration() -> None:
    settings = Settings(_env_file=None, wecom_mode="live", wecom_corp_id="corp-test")
    with pytest.raises(WeComConfigurationError, match="wecom_live_configuration_incomplete"):
        create_wecom_adapter(settings)

    with pytest.raises(ValidationError, match="SMARTSCAN_WECOM_MODE"):
        Settings(_env_file=None, wecom_mode="unknown")


def test_production_live_mode_requires_all_wecom_secrets() -> None:
    settings = Settings(
        _env_file=None,
        env="production",
        secret_key="s" * 32,
        phone_hmac_peppers={"v1": "p" * 32},
        phone_hmac_active_key_id="v1",
        phone_encryption_keys={"v1": base64.urlsafe_b64encode(b"k" * 32).decode()},
        phone_encryption_active_key_id="v1",
        superadmin_password="strong-bootstrap-password",
        wecom_mode="live",
        wecom_corp_id="corp-test",
    )
    with pytest.raises(RuntimeError, match="live WeCom configuration is incomplete"):
        settings.validate_production()
