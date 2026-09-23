class NewsAnalyzer:

    POSITIVE_SIGNALS = {
        "beats estimates": 3,
        "beat estimates": 3,
        "raises guidance": 4,
        "raised guidance": 4,
        "record revenue": 4,
        "record profit": 4,
        "approval": 3,
        "approved": 3,
        "partnership": 2,
        "buyback": 3,
        "share repurchase": 3,
        "dividend increase": 3,
        "upgrade": 2,
        "upgraded": 2,
        "strong demand": 3,
        "revenue growth": 2,
        "profit growth": 2,
        "wins contract": 3,
        "new contract": 2,
        "expands": 1,
        "expansion": 1,
    }

    NEGATIVE_SIGNALS = {
        "misses estimates": 3,
        "missed estimates": 3,
        "cuts guidance": 4,
        "cut guidance": 4,
        "downgrade": 2,
        "downgraded": 2,
        "lawsuit": 3,
        "investigation": 3,
        "probe": 3,
        "ban": 4,
        "banned": 4,
        "recall": 4,
        "layoffs": 2,
        "job cuts": 2,
        "weak demand": 3,
        "revenue decline": 3,
        "profit decline": 3,
        "loss widens": 3,
        "regulatory pressure": 3,
        "regulatory risk": 3,
        "supply disruption": 3,
        "production halt": 4,
        "fraud": 5,
        "default": 5,
    }

    def analyze(
        self,
        title: str,
        summary: str | None = None,
        symbol: str | None = None,
        name: str | None = None,
    ) -> dict:

        text = " ".join(
            part
            for part in [
                title,
                summary,
            ]
            if part
        ).lower()

        positive_matches = []
        negative_matches = []

        positive_score = 0
        negative_score = 0

        for phrase, weight in (
            self.POSITIVE_SIGNALS.items()
        ):

            if phrase in text:

                positive_matches.append(
                    phrase
                )

                positive_score += weight

        for phrase, weight in (
            self.NEGATIVE_SIGNALS.items()
        ):

            if phrase in text:

                negative_matches.append(
                    phrase
                )

                negative_score += weight

        net_score = (
            positive_score
            - negative_score
        )

        if net_score > 0:

            sentiment = "positive"

            strength = positive_score

            reason = (
                "Positive signals: "
                + ", ".join(
                    positive_matches
                )
            )

        elif net_score < 0:

            sentiment = "negative"

            strength = negative_score

            reason = (
                "Negative signals: "
                + ", ".join(
                    negative_matches
                )
            )

        else:

            sentiment = "neutral"

            strength = max(
                positive_score,
                negative_score,
            )

            if (
                positive_matches
                or negative_matches
            ):

                reason = (
                    "Mixed positive and "
                    "negative signals."
                )

            else:

                reason = (
                    "No strong market-impact "
                    "keywords detected."
                )

        if strength == 0:

            impact_score = 10

        else:

            impact_score = min(
                100,
                20 + strength * 12,
            )

        return {
            "sentiment":
                sentiment,

            "impact_score":
                impact_score,

            "reason":
                reason,

            "positive_signals":
                positive_matches,

            "negative_signals":
                negative_matches,

            "symbol":
                symbol,

            "name":
                name,
        }