from __future__ import annotations

from dataclasses import dataclass

from aiogram import BaseMiddleware

from quizhub.config import Settings
from quizhub.db import Database


@dataclass
class AppContext:
    db: Database
    settings: Settings
    bot_username: str = ""


class ContextMiddleware(BaseMiddleware):
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    async def __call__(self, handler, event, data):
        data["ctx"] = self.ctx
        data["db"] = self.ctx.db
        data["settings"] = self.ctx.settings
        return await handler(event, data)
