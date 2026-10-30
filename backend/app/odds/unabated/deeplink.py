"""Gambly deep-link partner attribution for Unabated Free API."""

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def attach_partner_code(deep_link: str | None, partner_code: str | None) -> str | None:
    if not deep_link or not partner_code:
        return deep_link
    parsed = urlparse(deep_link)
    if not parsed.scheme:
        return deep_link
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["utm_campaign"] = partner_code
    return urlunparse(parsed._replace(query=urlencode(query)))
