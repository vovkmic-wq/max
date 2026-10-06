"""RSS, HTML and authorized messenger collectors."""

import calendar
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

import feedparser
from bs4 import BeautifulSoup

from .config import AgentError
from .network import canonical_url


@dataclass
class Item:
    external_id: str
    title: str
    text: str
    url: str
    published_at: float | None = None
    language: str = "auto"
    media: list = field(default_factory=list)


def clean_html(text):
    soup = BeautifulSoup(text, "html.parser")
    for node in soup.select("script,style,nav,footer,header,aside"):
        node.decompose()
    return " ".join(soup.get_text(" ").split())


def detect_language(text):
    text = re.sub(r"https?://\S+", "", text)
    ru = len(re.findall("[а-яА-ЯёЁ]", text))
    latin = len(re.findall("[a-zA-Z]", text))
    return "ru" if ru > latin else "en"


def collect_web(source, cursor, http, root):
    headers = {}
    if cursor.get("etag"):
        headers["If-None-Match"] = cursor["etag"]
    if cursor.get("last_modified"):
        headers["If-Modified-Since"] = cursor["last_modified"]
    status, content, returned_headers, url = http.get(source["endpoint"], headers)
    if status == 304:
        return [], cursor
    items = []
    if source["type"] == "rss":
        feed = feedparser.parse(content)
        if not feed.entries and (feed.bozo or not feed.feed):
            raise AgentError("INVALID_FEED")
        for entry in feed.entries[: source["max_items_per_run"]]:
            link = entry.get("link", "")
            if not link:
                continue
            text = clean_html(entry.get("summary", entry.get("description", "")))
            if source["full_text"] and entry.get("content"):
                text = clean_html(entry.content[0].get("value", text))
            time = entry.get("published_parsed")
            if time is None:
                time = entry.get("updated_parsed")
            published = calendar.timegm(time) if time else None
            items.append(
                Item(
                    str(entry.get("id", link)),
                    entry.get("title", ""),
                    text,
                    canonical_url(link),
                    published,
                    source["language_hint"],
                    [
                        {"url": e.get("href", ""), "mime": e.get("type", "")}
                        for e in entry.get("enclosures", [])
                        if e.get("type", "").startswith("video/")
                    ],
                )
            )
    elif source["type"] == "html":
        from .config import inside, parse_json

        profile_path = inside(root, f"config/extraction/{source['extraction_profile']}.json")
        if not profile_path.exists():
            raise AgentError("EXTRACTION_PROFILE_MISSING")
        profile = parse_json(profile_path.read_text(encoding="utf-8-sig"))
        soup = BeautifulSoup(content, "html.parser")
        body, title = (
            soup.select_one(profile["body_selector"]),
            soup.select_one(profile["title_selector"]),
        )
        if not body or not title:
            raise AgentError("ARTICLE_SELECTOR_NO_MATCH")
        published = None
        if profile.get("date_selector"):
            node = soup.select_one(profile["date_selector"])
            if node and node.get("datetime"):
                try:
                    dt = datetime.fromisoformat(node["datetime"].replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        raise ValueError
                    published = dt.astimezone(UTC).timestamp()
                except ValueError:
                    published = None
        items.append(
            Item(
                url,
                clean_html(str(title)),
                clean_html(str(body)),
                url,
                published,
                source["language_hint"],
            )
        )
    else:
        raise AgentError("UNSUPPORTED_SOURCE")
    return items, {
        "etag": returned_headers.get("etag"),
        "last_modified": returned_headers.get("last-modified"),
    }


def messenger_items(platform, payload, source):
    if platform == "telegram":
        message = payload.get("channel_post") or payload.get("edited_channel_post")
        if not message or str(message.get("chat", {}).get("id")) != source["external_chat_id"]:
            return []
        text = message.get("text", message.get("caption", ""))
        mid = str(message["message_id"])
        username = message.get("chat", {}).get("username")
        link = f"https://t.me/{username}/{mid}" if username else ""
        return [
            Item(
                mid,
                text.split("\n")[0][:200],
                text,
                link,
                message.get("date"),
                detect_language(text),
            )
        ]
    message = payload.get("message", {})
    if str(message.get("recipient", {}).get("chat_id")) != source["external_chat_id"]:
        return []
    body = message.get("body", {})
    text = body.get("text", "")
    return [
        Item(
            str(body.get("mid", "")),
            text.split("\n")[0][:200],
            text,
            message.get("url", ""),
            message.get("timestamp", 0) / 1000 or None,
            detect_language(text),
        )
    ]
