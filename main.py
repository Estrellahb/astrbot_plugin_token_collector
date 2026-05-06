from __future__ import annotations

import os
import uuid

import aiohttp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register


@register(
    "astrbot_plugin_token_collector",
    "Token 用量采集器",
    "采集 LLM token 用量上报到管理后台",
    "2.0.0",
)
class TokenCollectorPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.backend_url = os.environ.get(
            "TOKEN_COLLECTOR_BACKEND_URL",
            "http://127.0.0.1:8848",
        ).rstrip("/")
        self.report_endpoint = f"{self.backend_url}/api/v1/token/report"
        logger.info(f"TokenCollectorPlugin 已加载，上报地址: {self.report_endpoint}")

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        """LLM 请求完成后，截获 token 用量并上报。"""
        if not resp or not resp.usage:
            return

        provider = self.context.get_using_provider(event.unified_msg_origin)
        provider_config = getattr(provider, "provider_config", {}) or {}
        usage = resp.usage
        provider_id = str(provider_config.get("id", "")).strip() or "unknown"
        provider_model = (
            getattr(provider, "get_model", lambda: "")() if provider else ""
        ) or str(provider_config.get("model", "")).strip() or "unknown"
        token_input_cached = int(getattr(usage, "input_cached", 0) or 0)
        token_input_other = int(getattr(usage, "input_other", 0) or 0)
        token_output = int(getattr(usage, "output", 0) or 0)
        request_id = getattr(resp, "id", None) or uuid.uuid4().hex

        payload = {
            "platform": "weixin_oc",
            "session_id": event.unified_msg_origin,
            "conversation_id": event.unified_msg_origin,
            "user_id": event.get_sender_id(),
            "request_id": str(request_id),
            "provider_id": provider_id,
            "provider_model": provider_model,
            "token_input_cached": token_input_cached,
            "token_input_other": token_input_other,
            "token_output": token_output,
            "status": "completed",
            "source": "plugin",
        }

        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.report_endpoint, json=payload) as response:
                    if response.status >= 400:
                        body = await response.text()
                        logger.error(
                            f"Token 上报失败: status={response.status}, body={body}, payload={payload}"
                        )
        except Exception as exc:
            logger.error(f"Token 上报失败: {exc}")
