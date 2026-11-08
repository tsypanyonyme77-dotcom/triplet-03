from typing import Any

from brain.adapters.guardian_rest import RestGuardianAdapter
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


__all__ = ["HttpTwinAdapter", "McpTwinAdapter", "MqttTwinAdapter", "RestGuardianAdapter", "open_twin"]
