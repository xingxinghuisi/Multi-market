from providers.binance import BinanceSpotProvider
from providers.krx import KRXProvider


class ProviderRegistry:

    def __init__(self):

        self._providers = {
            "BINANCE": BinanceSpotProvider(),
            "PYKRX": KRXProvider(),
        }

    def get(self, provider_name: str):

        if not provider_name:
            raise ValueError(
                "Provider name is required"
            )

        provider_name = (
            provider_name
            .strip()
            .upper()
        )

        provider = self._providers.get(
            provider_name
        )

        if provider is None:
            raise ValueError(
                f"Unsupported provider: "
                f"{provider_name}"
            )

        return provider

    def has(self, provider_name: str):

        if not provider_name:
            return False

        return (
            provider_name
            .strip()
            .upper()
            in self._providers
        )


provider_registry = ProviderRegistry()