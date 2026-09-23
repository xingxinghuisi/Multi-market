import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field


class AINewsAnalysis(BaseModel):

    sentiment: Literal[
        "positive",
        "negative",
        "neutral",
    ]

    impact_score: int = Field(
        ge=0,
        le=100,
    )

    relevance_score: int = Field(
        ge=0,
        le=100,
    )

    reason: str


class AINewsAnalyzer:

    def __init__(
        self,
        model: str | None = None,
    ):

        self.model = (
            model
            or os.getenv(
                "OPENAI_NEWS_MODEL",
                "gpt-5.6-luna",
            )
        )

        self.client = OpenAI()

    def analyze(
        self,
        title: str,
        summary: str | None = None,
        symbol: str | None = None,
        name: str | None = None,
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

        response = (
            self.client.responses.parse(
                model=self.model,

                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are a financial news "
                            "impact classifier.\n\n"

                            "Analyze the likely market "
                            "impact of the supplied news "
                            "on the TARGET ASSET only.\n\n"

                            "Rules:\n"
                            "1. Analyze market impact, "
                            "not emotional tone.\n"
                            "2. positive = likely beneficial "
                            "to the target asset.\n"
                            "3. negative = likely harmful "
                            "to the target asset.\n"
                            "4. neutral = unclear, mixed, "
                            "irrelevant, or insufficient "
                            "information.\n"
                            "5. impact_score is 0-100. "
                            "0 means essentially no expected "
                            "impact; 100 means potentially "
                            "major impact.\n"
                            "6. relevance_score is 0-100 "
                            "for how directly the news "
                            "concerns the target asset.\n"
                            "7. Use ONLY the supplied title "
                            "and summary. Do not invent facts "
                            "from the unseen article.\n"
                            "8. If information is insufficient, "
                            "prefer neutral and a low score.\n"
                            "9. Explain the reason briefly "
                            "in Chinese."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Target symbol: {symbol}\n"
                            f"Target name: {name}\n\n"
                            f"Title:\n{title}\n\n"
                            f"Summary:\n"
                            f"{summary or '(none)'}"
                        ),
                    },
                ],

                text_format=AINewsAnalysis,
            )
        )

        result = (
            response.output_parsed
        )

        if result is None:

            raise RuntimeError(
                "AI returned no parsed result"
            )

        sentiment = result.sentiment
        impact_score = result.impact_score

        # 防止明显无关的新闻被打成利好/利空
        if result.relevance_score < 30:

            sentiment = "neutral"
            impact_score = 0

        return {
            "sentiment":
                sentiment,

            "impact_score":
                impact_score,

            "relevance_score":
                result.relevance_score,

            "reason":
                result.reason,

            "model":
                self.model,
        }