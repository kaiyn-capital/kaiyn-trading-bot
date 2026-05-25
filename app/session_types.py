import base64
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal

SESSION_PAYLOAD_VERSION = 1
MAX_SESSION_CHART_BYTES = 4 * 1024 * 1024

ApiSetupStep = Literal["api_key", "secret_key", "passphrase"]
ChannelSessionStep = Literal["manage_channels", "delete_channel"]


@dataclass(frozen=True)
class SessionMappingMixin:
    def to_legacy_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    def __getitem__(self, key: str) -> Any:
        return self.to_legacy_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_legacy_dict().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.to_legacy_dict()


@dataclass(frozen=True)
class ApiSetupSession(SessionMappingMixin):
    step: ApiSetupStep
    api_key: str | None = None
    secret_key: str | None = None
    expires_at: datetime | None = None

    def to_legacy_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"step": self.step, "expires_at": self.expires_at}
        if self.api_key is not None:
            data["api_key"] = self.api_key
        if self.secret_key is not None:
            data["secret_key"] = self.secret_key
        return data


@dataclass(frozen=True)
class RiskAmountSession(SessionMappingMixin):
    step: Literal["risk_amount"] = "risk_amount"
    expires_at: datetime | None = None

    def to_legacy_dict(self) -> dict[str, Any]:
        return {"step": self.step, "expires_at": self.expires_at}


@dataclass(frozen=True)
class ChannelManagementSession(SessionMappingMixin):
    channels_data: list[dict[str, Any]]
    step: ChannelSessionStep = "manage_channels"
    expires_at: datetime | None = None

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "channels_data": self.channels_data,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class SignalPreviewSession(SessionMappingMixin):
    token: str
    signal_record_id: int
    signal_public_id: str
    chart_status: str
    chart_error: str | None = None
    chart_bytes: bytes | None = None
    step: Literal["signal_preview"] = "signal_preview"
    expires_at: datetime | None = None

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "token": self.token,
            "signal_record_id": self.signal_record_id,
            "signal_public_id": self.signal_public_id,
            "chart_status": self.chart_status,
            "chart_error": self.chart_error,
            "chart_bytes": self.chart_bytes,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class ChartUpdatePreviewSession(SessionMappingMixin):
    token: str
    signal_record_id: int
    signal_public_id: str
    update_text: str
    chart_bytes: bytes
    step: Literal["chart_update_preview"] = "chart_update_preview"
    expires_at: datetime | None = None

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "token": self.token,
            "signal_record_id": self.signal_record_id,
            "signal_public_id": self.signal_public_id,
            "update_text": self.update_text,
            "chart_bytes": self.chart_bytes,
            "expires_at": self.expires_at,
        }


UserSessionPayload = (
    ApiSetupSession | RiskAmountSession | ChannelManagementSession | SignalPreviewSession | ChartUpdatePreviewSession
)


def coerce_session_payload(payload: UserSessionPayload | dict[str, Any]) -> UserSessionPayload:
    if not isinstance(payload, dict):
        return payload

    step = payload.get("step")
    if step in {"api_key", "secret_key", "passphrase"}:
        return ApiSetupSession(
            step=step,
            api_key=payload.get("api_key"),
            secret_key=payload.get("secret_key"),
        )
    if step == "risk_amount":
        return RiskAmountSession()
    if "channels_data" in payload:
        return ChannelManagementSession(
            step=step if step in {"manage_channels", "delete_channel"} else "manage_channels",
            channels_data=payload["channels_data"],
        )
    raise ValueError(f"unsupported legacy session payload: {payload!r}")


def session_type_for(payload: UserSessionPayload) -> str:
    if isinstance(payload, ApiSetupSession):
        return "api_setup"
    if isinstance(payload, RiskAmountSession):
        return "risk_amount"
    if isinstance(payload, ChannelManagementSession):
        return "channel_management"
    if isinstance(payload, SignalPreviewSession):
        return "signal_preview"
    if isinstance(payload, ChartUpdatePreviewSession):
        return "chart_update_preview"
    raise TypeError(f"Unsupported session payload: {type(payload).__name__}")


def session_token_for(payload: UserSessionPayload) -> str | None:
    if isinstance(payload, (SignalPreviewSession, ChartUpdatePreviewSession)):
        return payload.token
    return None


def with_session_expiry(payload: UserSessionPayload, expires_at: datetime) -> UserSessionPayload:
    return replace(payload, expires_at=expires_at)


def session_payload_to_json_data(payload: UserSessionPayload) -> dict[str, Any]:
    if isinstance(payload, ApiSetupSession):
        return {
            "step": payload.step,
            "api_key": payload.api_key,
            "secret_key": payload.secret_key,
        }
    if isinstance(payload, RiskAmountSession):
        return {"step": payload.step}
    if isinstance(payload, ChannelManagementSession):
        return {
            "step": payload.step,
            "channels_data": payload.channels_data,
        }
    if isinstance(payload, SignalPreviewSession):
        return {
            "step": payload.step,
            "token": payload.token,
            "signal_record_id": payload.signal_record_id,
            "signal_public_id": payload.signal_public_id,
            "chart_status": payload.chart_status,
            "chart_error": payload.chart_error,
            "chart_bytes": _encode_chart_bytes(payload.chart_bytes),
        }
    if isinstance(payload, ChartUpdatePreviewSession):
        return {
            "step": payload.step,
            "token": payload.token,
            "signal_record_id": payload.signal_record_id,
            "signal_public_id": payload.signal_public_id,
            "update_text": payload.update_text,
            "chart_bytes": _encode_chart_bytes(payload.chart_bytes),
        }
    raise TypeError(f"Unsupported session payload: {type(payload).__name__}")


def session_payload_from_json_data(
    session_type: str,
    data: dict[str, Any],
    expires_at: datetime | None = None,
) -> UserSessionPayload:
    if session_type == "api_setup":
        step = data.get("step")
        if step not in {"api_key", "secret_key", "passphrase"}:
            raise ValueError("invalid api setup session step")
        return ApiSetupSession(
            step=step,
            api_key=data.get("api_key"),
            secret_key=data.get("secret_key"),
            expires_at=expires_at,
        )
    if session_type == "risk_amount":
        return RiskAmountSession(expires_at=expires_at)
    if session_type == "channel_management":
        step = data.get("step", "manage_channels")
        if step not in {"manage_channels", "delete_channel"}:
            raise ValueError("invalid channel session step")
        channels_data = data.get("channels_data")
        if not isinstance(channels_data, list):
            raise ValueError("invalid channel session data")
        return ChannelManagementSession(
            step=step,
            channels_data=channels_data,
            expires_at=expires_at,
        )
    if session_type == "signal_preview":
        return SignalPreviewSession(
            token=str(data["token"]),
            signal_record_id=int(data["signal_record_id"]),
            signal_public_id=str(data["signal_public_id"]),
            chart_status=str(data.get("chart_status") or "disabled"),
            chart_error=data.get("chart_error"),
            chart_bytes=_decode_chart_bytes(data.get("chart_bytes")),
            expires_at=expires_at,
        )
    if session_type == "chart_update_preview":
        chart_bytes = _decode_chart_bytes(data.get("chart_bytes"))
        if chart_bytes is None:
            raise ValueError("chart update session missing chart bytes")
        return ChartUpdatePreviewSession(
            token=str(data["token"]),
            signal_record_id=int(data["signal_record_id"]),
            signal_public_id=str(data["signal_public_id"]),
            update_text=str(data["update_text"]),
            chart_bytes=chart_bytes,
            expires_at=expires_at,
        )
    raise ValueError(f"unsupported session type: {session_type}")


def _encode_chart_bytes(chart_bytes: bytes | None) -> str | None:
    if chart_bytes is None:
        return None
    if len(chart_bytes) > MAX_SESSION_CHART_BYTES:
        raise ValueError("session chart payload is too large")
    return base64.b64encode(chart_bytes).decode("ascii")


def _decode_chart_bytes(value: str | None) -> bytes | None:
    if value is None:
        return None
    chart_bytes = base64.b64decode(value.encode("ascii"))
    if len(chart_bytes) > MAX_SESSION_CHART_BYTES:
        raise ValueError("session chart payload is too large")
    return chart_bytes
