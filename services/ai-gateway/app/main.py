from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException

from .providers import ProviderDefinition, ProviderRegistry, create_adapter, load_provider_registry


@lru_cache
def get_registry() -> ProviderRegistry:
    return load_provider_registry()


def create_app() -> FastAPI:
    application = FastAPI(title="SmartScan 可选视觉 AI 网关", version="0.2.0")

    @application.get("/health")
    def health():
        registry = get_registry()
        return {
            "status": "ok",
            "enabled": registry.enabled_count > 0,
            "provider_count": len(registry.list_descriptors()),
            "enabled_count": registry.enabled_count,
            "ready_count": registry.ready_count,
        }

    @application.get("/v1/providers")
    def list_providers():
        return {"items": get_registry().list_descriptors()}

    @application.get("/v1/providers/{provider_id}")
    def get_provider(provider_id: str):
        try:
            return get_registry().get(provider_id).descriptor()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="provider_not_found") from exc

    @application.post("/v1/providers/check")
    def check_provider(payload: ProviderDefinition):
        adapter = create_adapter(payload, {})
        return {
            "accepted": True,
            "provider": adapter.descriptor(),
            "note": "configuration_only_no_network_request",
        }

    return application


app = create_app()
