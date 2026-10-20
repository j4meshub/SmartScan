"""企业微信身份与通讯录手机号适配器。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from .config import Settings
from .security import normalize_phone

WECOM_API_BASE_URL = "https://qyapi.weixin.qq.com"


class WeComAdapterError(RuntimeError):
    """仅暴露稳定错误码，避免把 OAuth code、Secret 或手机号带入日志。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class WeComConfigurationError(WeComAdapterError):
    pass


class WeComProviderError(WeComAdapterError):
    pass


@dataclass(frozen=True, slots=True)
class WeComIdentity:
    corp_id: str
    user_id: str
    phone_e164: str | None
    assurance: Literal["mock", "wecom_directory"]

    @property
    def provider_subject(self) -> str:
        return f"{self.corp_id}:{self.user_id}"

    @property
    def requires_phone_binding(self) -> bool:
        return self.phone_e164 is None


class WeComIdentityAdapter(Protocol):
    def resolve(self, oauth_code: str) -> WeComIdentity: ...


@dataclass(frozen=True, slots=True)
class WeComAccountDecision:
    action: Literal[
        "use_bound_identity",
        "bind_verified_phone",
        "create_wecom_user",
        "require_phone_binding",
        "require_conflict_review",
    ]
    canonical_user_id: str | None = None


def decide_wecom_account_action(
    identity: WeComIdentity,
    *,
    bound_identity_user_id: str | None,
    phone_candidate_user_ids: list[str],
) -> WeComAccountDecision:
    """定义 OAuth 回调后的安全账号决策，不在 POC 阶段直接修改数据库。"""

    if bound_identity_user_id:
        return WeComAccountDecision("use_bound_identity", bound_identity_user_id)
    if identity.phone_e164 is None:
        return WeComAccountDecision("require_phone_binding")

    candidates = set(phone_candidate_user_ids)
    if not candidates:
        return WeComAccountDecision("create_wecom_user")
    if len(candidates) == 1:
        return WeComAccountDecision("bind_verified_phone", candidates.pop())
    return WeComAccountDecision("require_conflict_review")


class DisabledWeComAdapter:
    def resolve(self, oauth_code: str) -> WeComIdentity:
        del oauth_code
        raise WeComConfigurationError("wecom_disabled")


class MockWeComAdapter:
    """本地契约替身；返回值明确标记为 mock，不能作为真实租户验收证据。"""

    def __init__(self, identities_by_code: dict[str, WeComIdentity] | None = None):
        self._identities_by_code = identities_by_code or {}

    def resolve(self, oauth_code: str) -> WeComIdentity:
        identity = self._identities_by_code.get(oauth_code)
        if identity is None:
            raise WeComProviderError("wecom_invalid_oauth_code")
        if identity.assurance != "mock":
            raise WeComConfigurationError("wecom_mock_assurance_required")
        return identity


class WeComHttpAdapter:
    """通过固定企业微信 API 域名换取可信成员身份和通讯录手机号。"""

    def __init__(
        self,
        *,
        corp_id: str,
        agent_id: str,
        secret: str,
        timeout_seconds: float = 5.0,
        client: httpx.Client | None = None,
    ):
        if not corp_id or not agent_id or not secret:
            raise WeComConfigurationError("wecom_live_configuration_incomplete")
        self.corp_id = corp_id
        self.agent_id = agent_id
        self._secret = secret
        self._client = client or httpx.Client(
            base_url=WECOM_API_BASE_URL,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._access_token: str | None = None
        self._access_token_valid_until = 0.0
        self._token_lock = threading.Lock()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def resolve(self, oauth_code: str) -> WeComIdentity:
        code = oauth_code.strip()
        if not code:
            raise WeComProviderError("wecom_invalid_oauth_code")
        access_token = self._get_access_token()
        auth_data = self._request_json(
            "/cgi-bin/auth/getuserinfo", {"access_token": access_token, "code": code}
        )
        user_id = self._field(auth_data, "UserId", "userid")
        if not user_id:
            if self._field(auth_data, "OpenId", "openid"):
                raise WeComProviderError("wecom_non_member_identity")
            raise WeComProviderError("wecom_identity_missing")

        member = self._request_json(
            "/cgi-bin/user/get", {"access_token": access_token, "userid": user_id}
        )
        member_user_id = self._field(member, "userid", "UserId")
        if member_user_id != user_id:
            raise WeComProviderError("wecom_member_mismatch")

        phone = self._field(member, "mobile")
        if phone:
            try:
                phone = normalize_phone(phone)
            except ValueError as exc:
                raise WeComProviderError("wecom_invalid_member_phone") from exc

        return WeComIdentity(
            corp_id=self.corp_id,
            user_id=user_id,
            phone_e164=phone,
            assurance="wecom_directory",
        )

    def _get_access_token(self) -> str:
        with self._token_lock:
            now = time.monotonic()
            if self._access_token and now < self._access_token_valid_until:
                return self._access_token
            data = self._request_json(
                "/cgi-bin/gettoken", {"corpid": self.corp_id, "corpsecret": self._secret}
            )
            access_token = self._field(data, "access_token")
            if not access_token:
                raise WeComProviderError("wecom_access_token_missing")
            expires_in = data.get("expires_in", 7200)
            if not isinstance(expires_in, int) or expires_in <= 0:
                raise WeComProviderError("wecom_access_token_expiry_invalid")
            self._access_token = access_token
            self._access_token_valid_until = now + max(1, expires_in - 120)
            return access_token

    def _request_json(self, path: str, params: dict[str, str]) -> dict[str, object]:
        try:
            response = self._client.get(path, params=params, follow_redirects=False)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WeComProviderError("wecom_provider_unavailable") from exc
        if not isinstance(data, dict):
            raise WeComProviderError("wecom_invalid_provider_response")
        errcode = data.get("errcode", 0)
        if errcode not in (0, None):
            raise WeComProviderError("wecom_api_error")
        return data

    @staticmethod
    def _field(data: dict[str, object], *names: str) -> str | None:
        for name in names:
            value = data.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None


def create_wecom_adapter(
    settings: Settings,
    *,
    client: httpx.Client | None = None,
    mock_identities: dict[str, WeComIdentity] | None = None,
) -> WeComIdentityAdapter:
    if settings.wecom_mode == "disabled":
        return DisabledWeComAdapter()
    if settings.wecom_mode == "mock":
        if settings.env != "development":
            raise WeComConfigurationError("wecom_mock_development_only")
        return MockWeComAdapter(mock_identities)
    if settings.wecom_mode == "live":
        return WeComHttpAdapter(
            corp_id=settings.wecom_corp_id,
            agent_id=settings.wecom_agent_id,
            secret=settings.wecom_secret,
            timeout_seconds=settings.wecom_timeout_seconds,
            client=client,
        )
    raise WeComConfigurationError("wecom_mode_invalid")
