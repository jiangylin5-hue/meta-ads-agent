"""Aggregated API router."""

from fastapi import APIRouter

from . import action_routes, admin_routes, agent_routes, config_routes
from . import memory_routes, meta_auth_routes, meta_read_routes, session_routes


router = APIRouter()
for child in (
    agent_routes.router,
    config_routes.router,
    admin_routes.router,
    meta_auth_routes.router,
    meta_read_routes.router,
    action_routes.router,
    memory_routes.router,
    session_routes.router,
):
    router.include_router(child)
