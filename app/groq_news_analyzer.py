import json
import os
import threading
import time

from groq import (
    Groq,
    RateLimitError,
)

_RATE_LOCK = threading.Lock()

_LAST_REQUEST_AT = 0.0

MIN_REQUEST_INTERVAL = 3.0


class GroqNewsAnalyzer:

    def __init__(
        self,
        model: str = "qwen/qwen3.8-27b",
    ):

        api_key = os.getenv(
            "GROQ_API_KEY"
        )

        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not configured"
            )

        self.model = model

        self.client = Groq(
            api_key=api_key
        )

    def _wait_for_rate_limit(
        self,
    ):

        global _LAST_REQUEST_AT

        with _RATE_LOCK:

            now = time.monotonic()

            elapsed = (
                now
                - _LAST_REQUEST_AT
            )

            wait_seconds = (
                MIN_REQUEST_INTERVAL
                - elapsed
            )

            if wait_seconds > 0:

                time.sleep(
                    wait_seconds
                )

            _LAST_REQUEST_AT = (
                time.monotonic()
            )

    def analyze(
            self,
            title: str,
            summary: str | None = None,
            symbol: str | None = None,
            name: str | None = None,
            asset_type: str | None = None,
            venue: str | None = None,
            segment: str | None = None,
            provider: str | None = None,
    ) -> dict:

        title = (
            title
            or ""
        ).strip()

        summary = (
            summary
            or ""
        ).strip()

        symbol = (
            symbol
            or ""
        ).strip()

        name = (
            name
            or ""
        ).strip()
        asset_type = (
                asset_type
                or ""
        ).strip()

        venue = (
                venue
                or ""
        ).strip()

        segment = (
                segment
                or ""
        ).strip()

        provider = (
                provider
                or ""
        ).strip()

        base_symbol = symbol

        if (
                symbol.upper()
                        .endswith("USDT")
        ):
            base_symbol = (
                symbol[:-4]
            )

        prompt = f"""
        你是金融新闻影响分析器。

        目标资产：

        交易代码：{symbol}
        基础代码：{base_symbol}
        名称：{name}
        系统资产分类：{asset_type}
        交易场所：{venue}
        交易分段：{segment}
        数据提供方：{provider}

        资产识别规则：

        1. 不要仅因为交易代码以 USDT 结尾，
           就判断目标资产一定是加密货币。

        2. 如果：
           venue = BINANCE
           且
           segment = FUTURES

           那么它是 Binance Futures 合约。
           它既可能对应加密资产，
           也可能对应股票、ETF、指数等
           TradFi-linked perpetual。

        3. asset_type 是系统内部分类，
           不能单独用于判断真实 underlying。

        4. 如果交易代码以 USDT 结尾，
           新闻可能只使用基础代码。

           例如：
           KORUUSDT -> KORU

           因此新闻只出现 KORU，
           不能仅因为没有出现 KORUUSDT
           就判断为无关。

        5. 但是必须区分同名但完全无关的实体。
           例如公司、ETF、代币、地点、
           品牌或普通英文单词可能重名。

        6. relevance_score 应首先判断新闻中的实体，
           是否确实对应这个合约的 underlying，
           然后再判断市场影响。

        新闻标题：
        {title}

        新闻摘要：
        {summary or "(无摘要)"}

        请判断这条新闻对“目标资产”本身的市场影响。

新闻摘要：
{summary or "(无摘要)"}

请判断这条新闻对“目标资产”本身的市场影响。

判断标准：

positive：
新闻可能对目标资产形成正面影响。

negative：
新闻可能对目标资产形成负面影响。

neutral：
影响不明确、信息不足、正负混合，
或者新闻实际上与目标资产没有直接关系。

impact_score：
0-100。
表示这条新闻对目标资产潜在影响的强弱，
不是股价涨跌百分比。

relevance_score：
0-100。
表示新闻与目标资产的直接相关程度。

只允许根据提供的标题和摘要判断。
不要假设没有提供的新闻正文内容。

reason：
使用简洁中文说明判断理由。
"""

        response = None

        max_attempts = 3

        for attempt in range(
                1,
                max_attempts + 1,
        ):

            self._wait_for_rate_limit()

            try:

                response = (
                    self.client
                    .chat
                    .completions
                    .create(
                        model=self.model,

                        messages=[
                            {
                                "role": "user",
                                "content": prompt,
                            }
                        ],

                        reasoning_effort="none",

                        reasoning_format="hidden",

                        response_format={
                            "type":
                                "json_schema",

                            "json_schema": {
                                "name":
                                    "news_analysis",

                                "strict":
                                    True,

                                "schema": {
                                    "type":
                                        "object",

                                    "properties": {
                                        "sentiment": {
                                            "type":
                                                "string",

                                            "enum": [
                                                "positive",
                                                "negative",
                                                "neutral",
                                            ],
                                        },

                                        "impact_score": {
                                            "type":
                                                "integer",

                                            "minimum":
                                                0,

                                            "maximum":
                                                100,
                                        },

                                        "relevance_score": {
                                            "type":
                                                "integer",

                                            "minimum":
                                                0,

                                            "maximum":
                                                100,
                                        },

                                        "reason": {
                                            "type":
                                                "string",
                                        },
                                    },

                                    "required": [
                                        "sentiment",
                                        "impact_score",
                                        "relevance_score",
                                        "reason",
                                    ],

                                    "additionalProperties":
                                        False,
                                },
                            },
                        },
                    )
                )

                break

            except RateLimitError:

                if attempt >= max_attempts:
                    raise

                # 第一次限流等 8 秒
                # 第二次限流等 16 秒
                wait_seconds = (
                        8 * attempt
                )

                time.sleep(
                    wait_seconds
                )

        if response is None:
            raise RuntimeError(
                "Groq returned no response"
            )

        content = (
            response
            .choices[0]
            .message
            .content
        )

        result = json.loads(
            content
        )

        # 相关度太低时，
        # 强制当成中性新闻
        if (
            result[
                "relevance_score"
            ]
            < 30
        ):

            result[
                "sentiment"
            ] = "neutral"

            result[
                "impact_score"
            ] = 0

        result[
            "model"
        ] = self.model

        return result