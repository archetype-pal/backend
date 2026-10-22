from datetime import timedelta
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
import pytest
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.common.tests.query_counts import assert_query_count_constant
from apps.publications.models import Comment, Partner, Publication
from apps.publications.tests.factories import (
    CarouselItemFactory,
    CommentFactory,
    EventFactory,
    PartnerFactory,
    PublicationFactory,
)
from apps.users.tests.factories import UserFactory


def _tiny_image(name="logo.png"):
    buf = BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


class CarouselItemAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.carousel_items = CarouselItemFactory.create_batch(3)

    def test_carousel_items_api(self):
        response = self.client.get("/api/v1/media/carousel-items/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3, response.data


class PartnerAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.partners = PartnerFactory.create_batch(3)

    def test_partners_api(self):
        response = self.client.get("/api/v1/media/partners/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3, response.data
        assert {"id", "name", "url", "logo", "ordering"} <= set(response.data[0].keys())


class PartnerManagementAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_authenticate(self.superuser)

    def test_create_partner(self):
        payload = {"name": "Test Partner", "url": "https://example.org", "logo": _tiny_image()}
        response = self.client.post("/api/v1/media/management/partners/", payload, format="multipart")
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Partner.objects.filter(name="Test Partner").exists()

    def test_update_partner_ordering(self):
        partner = PartnerFactory()
        response = self.client.patch(f"/api/v1/media/management/partners/{partner.id}/", {"ordering": 5}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.data
        partner.refresh_from_db()
        assert partner.ordering == 5

    def test_delete_partner(self):
        partner = PartnerFactory()
        response = self.client.delete(f"/api/v1/media/management/partners/{partner.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Partner.objects.filter(id=partner.id).exists()

    def test_anonymous_cannot_write(self):
        self.client.force_authenticate(None)
        response = self.client.post(
            "/api/v1/media/management/partners/",
            {"name": "x", "url": "", "logo": _tiny_image()},
            format="multipart",
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


class PublicationManagementAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_authenticate(self.superuser)

    def test_create_draft_with_minimal_payload_assigns_author(self):
        response = self.client.post(
            "/api/v1/media/management/publications/",
            {"title": "Draft Shell", "slug": "draft-shell"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        publication = Publication.objects.get(slug="draft-shell")
        assert publication.author == self.superuser
        assert publication.status == Publication.Status.DRAFT
        assert publication.content == ""
        assert publication.preview == ""
        assert response.data["author"] == self.superuser.id

    def test_create_ignores_client_supplied_author(self):
        other_user = UserFactory(is_staff=True, is_superuser=True)

        response = self.client.post(
            "/api/v1/media/management/publications/",
            {"title": "Owned Draft", "slug": "owned-draft", "author": other_user.id},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        publication = Publication.objects.get(slug="owned-draft")
        assert publication.author == self.superuser
        assert response.data["author"] == self.superuser.id

    def test_create_published_requires_content_and_preview(self):
        response = self.client.post(
            "/api/v1/media/management/publications/",
            {
                "title": "Incomplete Published Post",
                "slug": "incomplete-published-post",
                "status": Publication.Status.PUBLISHED,
                "content": "<p><br></p>",
                "preview": "<p>&nbsp;</p>",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "content" in response.data
        assert "preview" in response.data

    def test_update_to_published_requires_content_and_preview(self):
        publication = PublicationFactory(
            author=self.superuser,
            status=Publication.Status.DRAFT,
            content="",
            preview="",
        )

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {"status": Publication.Status.PUBLISHED},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "content" in response.data
        assert "preview" in response.data

    def test_update_to_published_with_content_and_preview_succeeds(self):
        publication = PublicationFactory(
            author=self.superuser,
            status=Publication.Status.DRAFT,
            content="",
            preview="",
        )

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {
                "status": Publication.Status.PUBLISHED,
                "content": "<p>Body text</p>",
                "preview": "<p>Preview text</p>",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        publication.refresh_from_db()
        assert publication.status == Publication.Status.PUBLISHED
        assert publication.content == "<p>Body text</p>"
        assert publication.preview == "<p>Preview text</p>"

    def test_keywords_round_trip_as_a_string(self):
        publication = PublicationFactory(author=self.superuser)

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {"keywords": "charters, scribes"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        # The response must show the new tags, not the pre-write state.
        assert response.data["keywords"] == "charters, scribes"
        # Re-fetch rather than refresh_from_db(): the latter drops Tagulous'
        # tag-string cache without repopulating it, so str() would read blank.
        assert str(Publication.objects.get(pk=publication.pk).keywords) == "charters, scribes"

    def test_too_many_keywords_is_rejected_with_400(self):
        """Tagulous raises a bare ValueError on save once max_count is passed,
        which would surface as a 500. The field has to catch it first."""
        publication = PublicationFactory(author=self.superuser)
        max_count = Publication._meta.get_field("keywords").tag_options.max_count

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {"keywords": ", ".join(f"k{i}" for i in range(max_count + 1))},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert "keywords" in response.data
        publication.refresh_from_db()
        assert publication.keywords.count() == 0

    def test_keyword_count_follows_tagulous_space_delimiting(self):
        """Spaces delimit tags too, so counting commas would let a payload
        through that the save then rejects."""
        publication = PublicationFactory(author=self.superuser)

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {"keywords": "a b c d e f g h i j k"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data

    def test_blank_keywords_clears_the_tags(self):
        publication = PublicationFactory(author=self.superuser)
        publication.keywords = "one, two"
        publication.save()

        response = self.client.patch(
            f"/api/v1/media/management/publications/{publication.slug}/",
            {"keywords": ""},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.data["keywords"] == ""
        publication.refresh_from_db()
        assert publication.keywords.count() == 0

    def test_create_accepts_keywords(self):
        response = self.client.post(
            "/api/v1/media/management/publications/",
            {"title": "Tagged", "slug": "tagged", "keywords": "alpha, beta"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert Publication.objects.get(slug="tagged").keywords.count() == 2

    def test_publication_management_searches_title_and_slug(self):
        match = PublicationFactory(title="Special Charter Research", slug="special-research")
        PublicationFactory(title="Other General Post", slug="other-general-post")

        for term in ["Special Charter", "special-research"]:
            with self.subTest(term=term):
                res = self.client.get("/api/v1/media/management/publications/", {"search": term})
                assert [row["slug"] for row in res.data["results"]] == [match.slug]

    def test_publication_management_search_does_not_match_the_preview(self):
        PublicationFactory(title="Plain title", slug="plain-title", preview="<strong>bold</strong>")

        res = self.client.get("/api/v1/media/management/publications/?search=strong")

        assert res.data["count"] == 0

    def test_comment_management_searches_author_content_and_post_title(self):
        match = CommentFactory(
            author_name="AliceSmith",
            author_email="alice@abbey.example",
            content="Great charter observation",
            post=PublicationFactory(title="Melrose charters"),
        )
        CommentFactory(
            author_name="BobJones",
            author_email="bob@priory.example",
            content="Question regarding script",
            post=PublicationFactory(title="Kelso seals"),
        )

        for term in ["AliceSmith", "alice@abbey", "charter observation", "Melrose"]:
            with self.subTest(term=term):
                res = self.client.get("/api/v1/media/management/comments/", {"search": term})
                assert [row["id"] for row in res.data["results"]] == [match.id]

    def test_publication_management_sorts_by_comment_count(self):
        quiet, busy, middling = PublicationFactory.create_batch(3)
        CommentFactory.create_batch(2, post=busy)
        CommentFactory(post=middling)

        res = self.client.get("/api/v1/media/management/publications/?ordering=-comment_count")

        assert [row["slug"] for row in res.data["results"]] == [busy.slug, middling.slug, quiet.slug]


class EventsAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.events = EventFactory.create_batch(3)

    def test_events_list_api(self):
        response = self.client.get("/api/v1/media/events/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3, response.data

    def test_events_detail_api(self):
        event = self.events[0]
        response = self.client.get(f"/api/v1/media/events/{event.slug}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["slug"] == event.slug
        assert response.data["title"] == event.title


class PublicationsAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.publications = PublicationFactory.create_batch(3)

    def test_publications_list_api(self):
        publication = self.publications[0]
        publication.keywords = "palaeography, medieval"
        publication.is_blog_post = True
        publication.is_news = False
        publication.is_featured = True
        publication.save()

        response = self.client.get("/api/v1/media/publications/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 3, response.data
        result = next(r for r in response.data["results"] if r["id"] == publication.id)
        assert "keywords" in result
        assert "palaeography" in result["keywords"]
        assert result["is_blog_post"] is True
        assert result["is_news"] is False
        assert result["is_featured"] is True

    def test_publication_detail_api(self):
        publication = self.publications[0]
        publication.keywords = "charters, scribes"
        publication.is_blog_post = False
        publication.is_news = True
        publication.is_featured = True
        publication.save()

        response = self.client.get(f"/api/v1/media/publications/{publication.slug}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["slug"] == publication.slug
        assert response.data["title"] == publication.title
        assert "keywords" in response.data
        assert "charters" in response.data["keywords"]
        assert response.data["is_blog_post"] is False
        assert response.data["is_news"] is True
        assert response.data["is_featured"] is True

    def test_publications_list_does_not_query_keywords_per_row(self):
        """`keywords` is a m2m, so serializing it without a prefetch costs one
        query per publication."""

        def add_publications(n):
            for index in range(n):
                publication = PublicationFactory()
                publication.keywords = f"alpha{publication.pk}, beta{index}"
                publication.save()

        assert_query_count_constant(self.client, "/api/v1/media/publications/", add_publications)


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["is_news=true", "recent_posts=true"])
def test_public_publications_list_newest_first_and_undated_last(api_client, query):
    now = timezone.now()
    undated = PublicationFactory(is_news=True, published_at=None)
    older = PublicationFactory(is_news=True, published_at=now - timedelta(days=2))
    newer = PublicationFactory(is_news=True, published_at=now - timedelta(days=1))

    res = api_client.get(f"/api/v1/media/publications/?{query}")

    assert [row["slug"] for row in res.data["results"]] == [newer.slug, older.slug, undated.slug]


@pytest.mark.django_db
def test_publication_detail_lists_approved_comments_oldest_first_with_their_parent(api_client):
    post = PublicationFactory()
    now = timezone.now()
    question = CommentFactory(post=post, is_approved=True)
    answer = CommentFactory(post=post, parent=question, is_approved=True)
    CommentFactory(post=post, parent=question, is_approved=False)
    Comment.objects.filter(pk=question.pk).update(created_at=now - timedelta(days=2))
    Comment.objects.filter(pk=answer.pk).update(created_at=now - timedelta(days=1))

    res = api_client.get(f"/api/v1/media/publications/{post.slug}/")

    assert [(row["id"], row["parent"]) for row in res.data["comments"]] == [
        (question.id, None),
        (answer.id, question.id),
    ]


@pytest.mark.django_db
def test_publication_detail_does_not_query_per_reply(api_client):
    post = PublicationFactory()
    question = CommentFactory(post=post, is_approved=True)

    def add_replies(n):
        CommentFactory.create_batch(n, post=post, parent=question, is_approved=True)

    assert_query_count_constant(api_client, f"/api/v1/media/publications/{post.slug}/", add_replies)


def _comment_payload(**overrides):
    return {"author_name": "A. Reader", "author_email": "reader@example.org", "content": "Nice post", **overrides}


@pytest.mark.django_db
def test_anonymous_comment_waits_for_moderation(api_client):
    post = PublicationFactory()

    res = api_client.post(f"/api/v1/media/publications/{post.slug}/comments/", _comment_payload(), format="json")

    assert res.status_code == status.HTTP_201_CREATED, res.data
    assert Comment.objects.get(post=post).is_approved is False
    assert api_client.get(f"/api/v1/media/publications/{post.slug}/").data["comments"] == []


@pytest.mark.django_db
def test_comment_text_is_stored_as_escaped_paragraphs(api_client):
    post = PublicationFactory()
    payload = _comment_payload(content="<script>alert(1)</script>\n\nSecond paragraph")

    api_client.post(f"/api/v1/media/publications/{post.slug}/comments/", payload, format="json")

    assert Comment.objects.get(post=post).content == (
        "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>\n\n<p>Second paragraph</p>"
    )


@pytest.mark.django_db
def test_reply_to_an_approved_comment_keeps_its_parent(api_client):
    post = PublicationFactory()
    question = CommentFactory(post=post, is_approved=True)

    res = api_client.post(
        f"/api/v1/media/publications/{post.slug}/comments/", _comment_payload(parent=question.id), format="json"
    )

    assert res.status_code == status.HTTP_201_CREATED, res.data
    assert Comment.objects.get(pk=res.data["id"]).parent == question


@pytest.mark.django_db
@pytest.mark.parametrize("approved, same_post", [(False, True), (True, False)])
def test_reply_must_answer_an_approved_comment_on_the_same_publication(api_client, approved, same_post):
    post = PublicationFactory()
    parent = CommentFactory(post=post if same_post else PublicationFactory(), is_approved=approved)

    res = api_client.post(
        f"/api/v1/media/publications/{post.slug}/comments/", _comment_payload(parent=parent.id), format="json"
    )

    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "parent" in res.data
    assert not Comment.objects.filter(post=post).exclude(pk=parent.pk).exists()


@pytest.mark.django_db
def test_comment_needs_an_email(api_client):
    post = PublicationFactory()
    payload = _comment_payload()
    del payload["author_email"]

    res = api_client.post(f"/api/v1/media/publications/{post.slug}/comments/", payload, format="json")

    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "author_email" in res.data


@pytest.mark.django_db
def test_closed_comments_are_refused(api_client):
    post = PublicationFactory(allow_comments=False)

    res = api_client.post(f"/api/v1/media/publications/{post.slug}/comments/", _comment_payload(), format="json")

    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert not Comment.objects.filter(post=post).exists()
    assert api_client.get(f"/api/v1/media/publications/{post.slug}/").data["allow_comments"] is False


@pytest.mark.django_db
def test_draft_publications_take_no_comments(api_client):
    post = PublicationFactory(status=Publication.Status.DRAFT)

    res = api_client.post(f"/api/v1/media/publications/{post.slug}/comments/", _comment_payload(), format="json")

    assert res.status_code == status.HTTP_404_NOT_FOUND
    assert not Comment.objects.filter(post=post).exists()


@pytest.mark.django_db
def test_comment_management_names_the_comment_a_reply_answers(management_client):
    question = CommentFactory(author_name="A. Reader", content="<p>Which hand?</p>")
    answer = CommentFactory(post=question.post, parent=question)

    res = management_client.get("/api/v1/media/management/comments/")

    rows = {row["id"]: row for row in res.data["results"]}
    assert (rows[answer.id]["parent_author_name"], rows[answer.id]["parent_content"]) == (
        "A. Reader",
        "<p>Which hand?</p>",
    )
    assert (rows[question.id]["parent_author_name"], rows[question.id]["parent_content"]) == (None, None)


@pytest.mark.django_db
def test_comment_management_does_not_query_parents_per_row(management_client):
    question = CommentFactory()

    def add_replies(n):
        CommentFactory.create_batch(n, post=question.post, parent=question)

    assert_query_count_constant(management_client, "/api/v1/media/management/comments/", add_replies)


@pytest.mark.django_db
def test_comment_management_gives_the_slug_of_the_commented_post(management_client):
    comment = CommentFactory(post=PublicationFactory(slug="modelling-codicology"))

    res = management_client.get("/api/v1/media/management/comments/")

    assert [(row["id"], row["post_slug"]) for row in res.data["results"]] == [(comment.id, "modelling-codicology")]


@pytest.mark.django_db
def test_publication_detail_keeps_hidden_comments_that_have_shown_replies(api_client):
    post = PublicationFactory()
    question = CommentFactory(post=post, is_approved=True)
    hidden = CommentFactory(post=post, parent=question, is_approved=False)
    answer = CommentFactory(post=post, parent=hidden, is_approved=True)
    hidden_alone = CommentFactory(post=post, is_approved=False)
    CommentFactory(post=post, parent=hidden_alone, is_approved=False)
    now = timezone.now()
    for days, comment in enumerate([answer, hidden, question], start=1):
        Comment.objects.filter(pk=comment.pk).update(created_at=now - timedelta(days=days))

    res = api_client.get(f"/api/v1/media/publications/{post.slug}/")

    assert [(row["id"], row["parent"], row["removed"]) for row in res.data["comments"]] == [
        (question.id, None, False),
        (hidden.id, question.id, True),
        (answer.id, hidden.id, False),
    ]
    assert res.data["comments"][1] == {"id": hidden.id, "parent": question.id, "removed": True}
    assert res.data["number_of_comments"] == 2
