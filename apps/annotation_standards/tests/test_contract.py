"""The contract every IIIF and W3C route keeps with external clients: public, JSON-LD whatever the
Accept header, readable from any origin, and every link a client is told to follow resolves.

The routes come from the two URL modules, so a new route is covered, or fails here for want of
an id, the day it is added.
"""

import json

from django.urls import URLPattern, reverse
import pytest

from apps.annotation_standards import urls_iiif, urls_w3c
from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ItemImageFactory, image_text, text_region
from apps.scribes.tests.factories import HandFactory
from apps.symbols_structure.tests.factories import AllographFactory

pytestmark = pytest.mark.django_db

ROUTES: list[URLPattern] = [*urls_iiif.urlpatterns, *urls_w3c.urlpatterns]
THIRD_PARTY = "https://projectmirador.org"


@pytest.fixture
def corpus():
    """One image with a glyph and a text region, and a live text linking to the region."""
    image = ItemImageFactory()
    glyph = GraphFactory(item_image=image, allograph=AllographFactory(), hand=HandFactory())
    region = text_region(image)
    text = image_text(
        image, f'<p><seg type="salutation" corresp="#gid-{region.id}">salutem</seg></p>', status=ImageText.Status.LIVE
    )
    return {"item_part_id": image.item_part_id, "graph_id": glyph.id, "text_id": text.id}


def _url(route: URLPattern, corpus) -> str:
    kwargs = {name: corpus[name] for name in route.pattern.converters}
    url = reverse(route.name, kwargs=kwargs)
    return f"{url}?q=salutem" if route.name == "iiif-content-search" else url


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
@pytest.mark.parametrize(
    "accept",
    [
        "application/ld+json",
        'application/ld+json;profile="http://www.w3.org/ns/anno.jsonld"',
        "application/json",
        "*/*",
        # A browser's default Accept must not negotiate away the JSON-LD.
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        # Mirador 3's request preprocessor sends Accept: '' to non-first-party hosts.
        "",
    ],
)
def test_every_route_serves_json_ld_whatever_the_accept_header(api_client, corpus, route, accept):
    res = api_client.get(_url(route, corpus), HTTP_ACCEPT=accept)

    assert res.status_code == 200
    assert res["Content-Type"] == "application/ld+json"
    json.loads(res.content)


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_every_route_is_readable_from_any_origin(api_client, corpus, route):
    res = api_client.get(_url(route, corpus), HTTP_ORIGIN=THIRD_PARTY)

    assert res.status_code == 200
    assert res["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_every_route_answers_cors_preflight(api_client, corpus, route):
    """Viewers sending a non-safelisted header trigger an OPTIONS preflight."""
    res = api_client.options(
        _url(route, corpus),
        HTTP_ORIGIN=THIRD_PARTY,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="X-Requested-With,Cache-Control",
    )

    assert 200 <= res.status_code < 300
    assert res["Access-Control-Allow-Origin"] == "*"
    assert "GET" in res["Access-Control-Allow-Methods"]
    # echoed back, or the browser rejects the preflight
    assert "X-Requested-With" in res["Access-Control-Allow-Headers"]
    assert "Cache-Control" in res["Access-Control-Allow-Headers"]


def test_the_rest_of_the_api_keeps_its_origin_allowlist(api_client):
    res = api_client.get("/api/v1/symbols_structure/allographs/", HTTP_ORIGIN=THIRD_PARTY)

    assert res.status_code == 200
    assert "Access-Control-Allow-Origin" not in res


def _followable_links(document: dict, host: str) -> set[str]:
    """The links on this host a client is told to follow: the document's own id, every `source`
    (an annotation body's classification, a text target) and the id of each service it offers.

    Embedded canvas and annotation ids are identifiers, which IIIF and W3C do not require to
    resolve; the image server's URLs are not this host's.
    """
    links = {document["id"]} if "id" in document else set()

    def walk(node, key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for item in node:
                walk(item, key)
        elif isinstance(node, str) and key == "source":
            links.add(node)

    walk(document)
    for service in document.get("service", []):
        links.add(service["id"])
    return {link for link in links if link.startswith(host)}


def test_every_emitted_link_resolves(api_client, corpus):
    host = "http://testserver"
    followed: set[str] = set()

    for route in ROUTES:
        document = api_client.get(_url(route, corpus)).json()
        for link in _followable_links(document, host) - followed:
            followed.add(link)
            assert api_client.get(link.removeprefix(host)).status_code == 200, link

    # The walk saw each kind of link: a glyph's allograph and a text target, as well as the documents.
    assert any("/symbols_structure/allographs/" in link for link in followed)
    assert any("/manuscripts/image-texts/" in link for link in followed)
