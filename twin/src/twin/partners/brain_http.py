"""The City Brain's plain HTTP carrier (its `twin.adapter: http`): the same operations as its MCP tools.

    GET  /readings?cursor=&limit=  -> {readings, next_cursor, stream_id}   signed readings, oldest first
    GET  /topology                 -> zones, adjacency, exits, facilities, sensors
    GET  /capabilities             -> {action: description} of what it may call here
    POST /actuators/{action}       <- its signed actuator call  -> the actuator's result, flat
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Query

from twin.actuation import CallRefused
from twin.city.base import CitySource
from twin.partners.brain_calls import BrainDoor, capabilities
from twin.partners.reading_log import MAX_PAGE, ReadingLog
from twin.partners.topology import topology


def brain_router(log: ReadingLog, city: CitySource, door: BrainDoor) -> APIRouter:
    router = APIRouter(tags=["city brain"])

    @router.get("/readings")
    def readings(cursor: int = Query(0, ge=0), limit: int = Query(200, ge=0, le=MAX_PAGE)):
        """Signed readings from `cursor` on (the absolute position in this Twin's stream), oldest first."""
        return log.page(cursor, limit)

    @router.get("/topology")
    def get_topology():
        return topology(city)

    @router.get("/capabilities")
    def get_capabilities():
        return capabilities()

    @router.post("/actuators/{action}")
    async def actuator(action: str, call: Any = Body(...), x_api_key: str | None = Header(default=None)):
        # async on purpose: runs on the event loop, never in the middle of a tick that changes the city
        try:
            return door.handle(action, call, x_api_key)
        except CallRefused as exc:
            raise HTTPException(exc.status_code, exc.detail)

    return router
