from typing import Any

from brain.adapters.guardian_rest import RestGuardianAdapter
from brain.adapters.guardian_v1 import GuardianGateway, GuardianV1Adapter
from brain.adapters.tls import twin_target
from brain.adapters.twin_http import HttpTwinAdapter
from brain.adapters.twin_mcp import McpTwinAdapter
from brain.adapters.twin_mqtt import MqttTwinAdapter


def open_twin(config: Any, stop_when_done: bool = False) -> McpTwinAdapter:
    """The Twin adapter `twin.adapter` names (`mcp`, `http` or `mqtt`), pointed at `twin.url`, with the TLS settings if any."""
    if config.adapter == "mqtt":
        return MqttTwinAdapter(config.url, config.mqtt, config.poll_interval_ms, stop_when_done, config.tls)
    if config.adapter == "http":
        return HttpTwinAdapter(config.url, config.poll_interval_ms, stop_when_done, config.tls)
    return McpTwinAdapter(twin_target(config.url, config.tls), config.poll_interval_ms, stop_when_done)


def open_guardian(config: Any, client: Any) -> RestGuardianAdapter | GuardianV1Adapter:
    """The Guardian adapter `guardian.adapter` names (`rest` or `v1`), on an already open client. A v1 Guardian's verdicts are checked against its signing
    key; if that key is named but not set the Brain stops here rather than trust unsigned verdicts."""
    if config.adapter != "v1":
        return RestGuardianAdapter("", client)
    from brain.config import secret

    key = secret(config.hmac_secret_env) if config.hmac_secret_env else None
    if config.hmac_secret_env and key is None:
        raise SystemExit(f"error: {config.hmac_secret_env} is not set, so the Guardian's verdicts cannot be checked (set it, or set guardian.hmac_secret_env: null for a trial)")
    return GuardianV1Adapter("", client, api_key=secret(config.api_key_env), hmac_secret=key, dispatcher_id=config.dispatcher_id)


def with_gateway(twin: Any, guardian: Any, config: Any) -> Any:
    """For a v1 Guardian that audits actuator calls: the Twin as the gate sees it. Anything else leaves the Twin as it is."""
    return GuardianGateway(twin, guardian) if config.adapter == "v1" and config.gateway else twin


__all__ = ["GuardianGateway", "GuardianV1Adapter", "HttpTwinAdapter", "McpTwinAdapter", "MqttTwinAdapter", "RestGuardianAdapter", "open_guardian", "open_twin", "with_gateway"]
