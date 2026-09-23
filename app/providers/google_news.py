import html
import re

from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


class GoogleNewsProvider:

    BASE_URL = (
        "https://news.google.com/rss/search"
    )

    USER_AGENT = (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/153 Safari/537.36"
    )

    def search(
        self,
        query: str,
        limit: int = 20,
        time_range: str = "1d",
        hl: str = "en-US",
        gl: str = "US",
        ceid: str = "US:en",
    ):

        query = query.strip()

        if not query:
            return []

        search_query = query

        if time_range:
            search_query += (
                f" when:{time_range}"
            )

        params = {
            "q": search_query,
            "hl": hl,
            "gl": gl,
            "ceid": ceid,
        }

        url = (
            f"{self.BASE_URL}?"
            f"{urlencode(params)}"
        )

        request = Request(
            url,
            headers={
                "User-Agent":
                    self.USER_AGENT,
            },
        )

        with urlopen(
            request,
            timeout=15,
        ) as response:

            raw_data = response.read()

        root = ET.fromstring(
            raw_data
        )

        channel = root.find(
            "channel"
        )

        if channel is None:
            return []

        results = []

        for item in channel.findall(
            "item"
        ):

            title = (
                item.findtext(
                    "title"
                )
                or ""
            ).strip()

            link = (
                item.findtext(
                    "link"
                )
                or ""
            ).strip()

            description = (
                    item.findtext(
                        "description"
                    )
                    or ""
            ).strip()

            if description:
                description = html.unescape(
                    description
                )

                description = re.sub(
                    r"<[^>]+>",
                    " ",
                    description,
                )

                description = re.sub(
                    r"\s+",
                    " ",
                    description,
                ).strip()

            published_text = (
                item.findtext(
                    "pubDate"
                )
                or ""
            ).strip()

            source_element = (
                item.find(
                    "source"
                )
            )

            source = (
                source_element.text.strip()
                if (
                    source_element
                    is not None
                    and source_element.text
                )
                else "Google News"
            )

            published_at = None

            if published_text:

                try:

                    published_at = (
                        parsedate_to_datetime(
                            published_text
                        )
                    )

                except (
                    TypeError,
                    ValueError,
                    OverflowError,
                ):

                    published_at = None

            if (
                not title
                or not link
            ):
                continue

            results.append(
                {
                    "source":
                        source,

                    "url":
                        link,

                    "title":
                        title,

                    "summary":
                        description or None,

                    "published_at":
                        published_at,
                }
            )

            if (
                len(results)
                >= limit
            ):
                break

        return results