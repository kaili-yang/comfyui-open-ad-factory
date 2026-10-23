"""Read a product page and pull out what an ad needs: name, description, price, brand and images.

Only the Python standard library is used so the node pack adds no dependencies.
Sources are tried from most to least structured: Shopify product JSON, schema.org
Product JSON-LD, then Open Graph / meta tags.
"""
import json
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TIMEOUT = 20


def http_get(url, accept="text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read(), resp.headers.get_content_charset() or "utf-8"


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.json_ld = []
        self.title = ""
        self._in_title = False
        self._in_ld = False
        self._ld_buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in_ld = True
            self._ld_buf = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_ld:
            self._in_ld = False
            self.json_ld.append("".join(self._ld_buf))

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._in_ld:
            self._ld_buf.append(data)


def _iter_ld_nodes(node):
    if isinstance(node, list):
        for n in node:
            yield from _iter_ld_nodes(n)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _iter_ld_nodes(node[key])


def _is_product(node):
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(isinstance(x, str) and x.lower() in ("product", "productgroup") for x in types)


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _image_urls(v):
    urls = []
    for item in _as_list(v):
        if isinstance(item, str):
            urls.append(item)
        elif isinstance(item, dict):
            u = item.get("url") or item.get("contentUrl") or item.get("src")
            if u:
                urls.append(u)
    return urls


def _clean(text, limit=1200):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def parse_product_html(html, base_url):
    """Parse a product page. Returns a dict with name, description, brand, price, currency, images, url."""
    parser = _PageParser()
    parser.feed(html)
    info = {"url": base_url, "name": "", "description": "", "brand": "", "price": "", "currency": "", "images": []}

    for raw in parser.json_ld:
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        for node in _iter_ld_nodes(data):
            if not _is_product(node):
                continue
            info["name"] = info["name"] or _clean(node.get("name", ""), 200)
            info["description"] = info["description"] or _clean(node.get("description", ""))
            brand = node.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name", "")
            info["brand"] = info["brand"] or _clean(brand if isinstance(brand, str) else "", 100)
            for offer in _as_list(node.get("offers")):
                if isinstance(offer, dict) and not info["price"]:
                    info["price"] = str(offer.get("price") or offer.get("lowPrice") or "")
                    info["currency"] = offer.get("priceCurrency", "")
            info["images"] += _image_urls(node.get("image"))

    m = parser.meta
    info["name"] = info["name"] or _clean(m.get("og:title") or m.get("twitter:title") or parser.title, 200)
    info["description"] = info["description"] or _clean(m.get("og:description") or m.get("description") or m.get("twitter:description", ""))
    info["brand"] = info["brand"] or _clean(m.get("og:site_name", ""), 100)
    info["price"] = info["price"] or m.get("product:price:amount") or m.get("og:price:amount", "")
    info["currency"] = info["currency"] or m.get("product:price:currency") or m.get("og:price:currency", "")
    info["images"] += [u for u in (m.get("og:image:secure_url"), m.get("og:image"), m.get("twitter:image")) if u]

    seen = set()
    images = []
    for u in info["images"]:
        u = urllib.parse.urljoin(base_url, u.strip())
        if u.startswith("//"):
            u = "https:" + u
        if u not in seen:
            seen.add(u)
            images.append(u)
    info["images"] = images
    return info


def parse_shopify_json(data, base_url):
    p = data.get("product", data)
    variants = p.get("variants") or [{}]
    return {
        "url": base_url,
        "name": _clean(p.get("title", ""), 200),
        "description": _clean(p.get("body_html", "")),
        "brand": _clean(p.get("vendor", ""), 100),
        "price": str(variants[0].get("price", "")),
        "currency": "",
        "images": [img["src"] for img in p.get("images", []) if img.get("src")],
    }


def fetch_product(url):
    """Fetch a product page and return parsed product info. Raises ValueError if nothing usable is found."""
    if not re.match(r"^https?://", url):
        raise ValueError(f"Product URL must start with http:// or https://, got: {url!r}")

    parsed = urllib.parse.urlparse(url)
    if "/products/" in parsed.path:
        shopify_url = urllib.parse.urlunparse(parsed._replace(path=parsed.path.rstrip("/") + ".json", query="", fragment=""))
        try:
            body, charset = http_get(shopify_url, accept="application/json")
            info = parse_shopify_json(json.loads(body.decode(charset, "replace")), url)
            if info["name"] and info["images"]:
                return info
        except (OSError, ValueError):
            pass

    body, charset = http_get(url)
    info = parse_product_html(body.decode(charset, "replace"), url)
    if not info["name"]:
        raise ValueError(f"Could not find a product name on {url}. The site may block scrapers; fill in the manual fields instead.")
    return info


def format_product_brief(info):
    lines = [f"Product: {info.get('name', '')}"]
    for key, label in (("brand", "Brand"), ("price", "Price"), ("description", "Description"), ("url", "URL")):
        value = info.get(key)
        if value:
            if key == "price" and info.get("currency"):
                value = f"{value} {info['currency']}"
            lines.append(f"{label}: {value}")
    return "\n".join(lines)
