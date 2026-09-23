from groq_news_analyzer import GroqNewsAnalyzer
from news_analyzer import NewsAnalyzer


class HybridNewsAnalyzer:

    def __init__(self):

        self.rule_analyzer = NewsAnalyzer()

        self.groq_analyzer = None
        self.groq_init_error = None

        try:
            self.groq_analyzer = GroqNewsAnalyzer()

        except Exception as error:
            # Groq 未配置或初始化失败时，
            # 不影响整个新闻系统运行。
            self.groq_analyzer = None
            self.groq_init_error = type(error).__name__

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

        fallback_reason = (
            self.groq_init_error
            or "groq_unavailable"
        )

        # 优先使用 Groq
        if self.groq_analyzer is not None:

            try:
                result = self.groq_analyzer.analyze(
                    title=title,
                    summary=summary,
                    symbol=symbol,
                    name=name,
                    asset_type=asset_type,
                    venue=venue,
                    segment=segment,
                    provider=provider,
                )

                result["analysis_source"] = "groq"
                result["fallback_reason"] = None

                return result

            except Exception as error:
                fallback_reason = type(error).__name__

        # Groq 不可用或运行失败：
        # 自动回退本地规则分析器
        result = self.rule_analyzer.analyze(
            title=title,
            summary=summary,
            symbol=symbol,
            name=name,
        )

        result["analysis_source"] = "rule"
        result["fallback_reason"] = fallback_reason
        result["relevance_score"] = None
        result["model"] = "rule-based"

        return result