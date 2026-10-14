import logging

from aiogram.types import ErrorEvent

from quizhub.handlers.admin import router as admin_router
from quizhub.handlers.common import router as common_router
from quizhub.handlers.middleware import AppContext, ContextMiddleware
from quizhub.handlers.schedule import router as schedule_router
from quizhub.handlers.search_flow import router as search_router
from quizhub.handlers.subscriptions import router as subscriptions_router
from quizhub.handlers.teamup import router as teamup_router

__all__ = ["AppContext", "setup_routers"]

log = logging.getLogger("quizhub")


def setup_routers(dispatcher, ctx: AppContext) -> None:
    dispatcher.update.middleware(ContextMiddleware(ctx))

    @dispatcher.error()
    async def on_error(event: ErrorEvent) -> None:
        log.exception("Сбой при обработке обновления", exc_info=event.exception)
        incoming = event.update.message
        if incoming is None and event.update.callback_query is not None:
            incoming = event.update.callback_query.message
        if incoming is None:
            return
        try:
            await incoming.answer("Не получилось выполнить команду. Попробуйте ещё раз.")
        except Exception:
            log.exception("Не удалось отправить сообщение об ошибке")

    dispatcher.include_router(admin_router)
    dispatcher.include_router(teamup_router)
    dispatcher.include_router(subscriptions_router)
    dispatcher.include_router(schedule_router)
    dispatcher.include_router(common_router)
    dispatcher.include_router(search_router)
    dispatcher["ctx"] = ctx
