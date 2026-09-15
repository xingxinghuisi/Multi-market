class ProviderRegistry:

    SUPPORTED_PROVIDERS = {
        "BINANCE",
        "PYKRX",
        "INFOWAY",
        "MOOMOO",
    }

    def __init__(self):

        # Provider 改为懒加载。
        # 只有真正调用 get() 时才创建实例。
        self._providers = {}

    def get(
        self,
        provider_name: str,
    ):

        name = (
            provider_name
            .strip()
            .upper()
        )

        # 已经创建过，直接复用
        if name in self._providers:

            return self._providers[
                name
            ]

        # =============================================
        # Binance
        # =============================================

        if name == "BINANCE":

            from providers.binance import (
                BinanceSpotProvider,
            )

            provider = (
                BinanceSpotProvider()
            )

        # =============================================
        # PyKRX
        #
        # 只有历史回填等真正需要 PyKRX 时
        # 才会 import / 初始化
        # =============================================

        elif name == "PYKRX":

            from providers.krx import (
                KRXProvider,
            )

            provider = (
                KRXProvider()
            )

        # =============================================
        # Infoway
        # =============================================

        elif name == "INFOWAY":

            from providers.infoway import (
                InfowayKoreaProvider,
            )

            provider = (
                InfowayKoreaProvider()
            )
        elif name == "MOOMOO":

            from providers.moomoo import (
                MoomooRealtimeProvider,
            )

            provider = (
                MoomooRealtimeProvider()
            )
        else:

            raise ValueError(
                "Unsupported provider: "
                f"{provider_name}"
            )

        self._providers[
            name
        ] = provider

        return provider

    def has(
        self,
        provider_name: str,
    ):

        name = (
            provider_name
            .strip()
            .upper()
        )

        return (
            name
            in self.SUPPORTED_PROVIDERS
        )


provider_registry = (
    ProviderRegistry()
)