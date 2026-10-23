from __future__ import annotations

import html
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any

from .config import WebConfig
from .errors import ToolError


def _domain_matches(hostname: str, allowed: tuple[str, ...]) -> bool:
    if "*" in allowed:
        return True
    host = hostname.lower().rstrip(".")
    return any(host == domain.lower() or host.endswith("." + domain.lower()) for domain in allowed)


def validate_web_url(url: str, config: WebConfig, *, provider: bool = False) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ToolError("Only HTTPS web URLs are allowed")
    if parsed.username or parsed.password:
        raise ToolError("Web URLs cannot contain credentials")
    if not provider and (not config.allowed_domains or not _domain_matches(parsed.hostname, config.allowed_domains)):
        raise ToolError(f"Web domain is not allowlisted: {parsed.hostname}")


class _RedirectValidator(urllib.request.HTTPRedirectHandler):
    def __init__(self, config: WebConfig, provider: bool):
        self.config = config
        self.provider = provider

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_web_url(newurl, self.config, provider=self.provider)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.ignored += 1
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


class _DuckDuckGoResults(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if tag == "a" and "result__a" in classes and attributes.get("href"):
            self._current = {"title": "", "url": attributes["href"]}

    def handle_data(self, data):
        if self._current is not None:
            self._current["title"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self._current is not None:
            self._current["title"] = " ".join(self._current["title"].split())
            self.results.append(self._current)
            self._current = None


class WebRuntime:
    def __init__(self, config: WebConfig):
        self.config = config

    def _fetch(self, url: str, *, provider: bool = False) -> tuple[str, str]:
        if not self.config.enabled:
            raise ToolError("Web tools are disabled in configuration")
        validate_web_url(url, self.config, provider=provider)
        request = urllib.request.Request(
            url, headers={"User-Agent": "local-agentic-ai-research/0.1", "Accept": "*/*"}
        )
        opener = urllib.request.build_opener(_RedirectValidator(self.config, provider))
        try:
            with opener.open(request, timeout=self.config.timeout_seconds) as response:
                final_url = response.geturl()
                validate_web_url(final_url, self.config, provider=provider)
                raw = response.read(self.config.max_bytes + 1)
                content_type = response.headers.get_content_type()
                charset = response.headers.get_content_charset() or "utf-8"
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Web request failed: {exc}") from exc
        if len(raw) > self.config.max_bytes:
            raise ToolError("Web response exceeds configured byte limit")
        text = raw.decode(charset, errors="replace")
        return text, content_type

    def fetch(self, url: str) -> dict[str, Any]:
        text, content_type = self._fetch(url)
        if content_type == "text/html":
            extractor = _TextExtractor()
            extractor.feed(text)
            text = extractor.text()
        return {"url": url, "content_type": content_type, "content": text, "untrusted": True}

    @staticmethod
    def _clean_result_url(url: str) -> str:
        if url.startswith("//"):
            url = "https:" + url
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
            target = urllib.parse.parse_qs(parsed.query).get("uddg")
            if target:
                return target[0]
        return html.unescape(url)

    def search(self, query: str) -> dict[str, Any]:
        if not query.strip() or len(query) > 500:
            raise ToolError("Search query must contain 1–500 characters")
        url = self.config.search_url.replace("{query}", urllib.parse.quote_plus(query))
        text, content_type = self._fetch(url, provider=True)
        results: list[dict[str, str]] = []
        if "xml" in content_type or text.lstrip().startswith(("<?xml", "<rss")):
            try:
                root = ET.fromstring(text)
                for item in root.findall(".//item"):
                    results.append(
                        {
                            "title": item.findtext("title", ""),
                            "url": item.findtext("link", ""),
                            "snippet": item.findtext("description", ""),
                        }
                    )
            except ET.ParseError as exc:
                raise ToolError(f"Search provider returned invalid XML: {exc}") from exc
        else:
            parser = _DuckDuckGoResults()
            parser.feed(text)
            results = parser.results
        cleaned = []
        for result in results:
            result["url"] = self._clean_result_url(result.get("url", ""))
            parsed = urllib.parse.urlparse(result["url"])
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            if self.config.allowed_domains and not _domain_matches(
                parsed.hostname, self.config.allowed_domains
            ):
                continue
            cleaned.append(result)
            if len(cleaned) >= self.config.max_results:
                break
        return {"query": query, "results": cleaned, "untrusted": True}
