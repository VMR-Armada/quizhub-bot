from quizhub.handlers.admin import router as admin_router
from quizhub.handlers.common import router as common_router
from quizhub.handlers.middleware import AppContext, ContextMiddleware
from quizhub.handlers.schedule import router as schedule_router
from quizhub.handlers.search_flow import router as search_router
from quizhub.handlers.subscriptions import router as subscriptions_router
from quizhub.handlers.teamup import router as teamup_router

__all__ = ["AppContext", "setup_routers"]


def setup_routers(dispatcher, ctx: AppContext) -> None:
    dispatcher.update.middleware(ContextMiddleware(ctx))
    dispatcher.include_router(admin_router)
    dispatcher.include_router(teamup_router)
    dispatcher.include_router(subscriptions_router)
    dispatcher.include_router(schedule_router)
    dispatcher.include_router(common_router)
    dispatcher.include_router(search_router)
    dispatcher["ctx"] = ctx
