from datetime import UTC, datetime
from io import StringIO
import json

from django.core.management import call_command
import pytest

from apps.publications.models import Comment
from apps.publications.tests.factories import PublicationFactory


def _post(post_id, created_at, *, parent=None, deleted=False, html="<p>Text</p>"):
    return {
        "id": post_id,
        "parent": parent,
        "name": "A. Reader",
        "createdAt": created_at,
        "deleted": deleted,
        "html": html,
    }


def _thread(publication, *posts):
    return {"1": {"identifier": f"BlogPost-{publication.pk}", "title": publication.title, "posts": list(posts)}}


def _import(tmp_path, threads, *flags):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(threads), encoding="utf-8")
    out = StringIO()
    call_command("import_disqus_comments", str(snapshot), *flags, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_dry_run_writes_nothing(tmp_path):
    publication = PublicationFactory()

    output = _import(tmp_path, _thread(publication, _post("10", "2012-08-07T10:00:00")))

    assert "DRY-RUN" in output
    assert not Comment.objects.exists()


@pytest.mark.django_db
def test_apply_keeps_replies_dates_and_approval(tmp_path):
    publication = PublicationFactory()
    threads = _thread(
        publication,
        _post("11", "2012-08-09T08:40:00", parent=10),
        _post("10", "2012-08-07T10:15:00"),
    )

    _import(tmp_path, threads, "--apply")

    question = Comment.objects.get(disqus_id="10")
    answer = Comment.objects.get(disqus_id="11")
    assert answer.parent == question
    assert question.post == publication
    assert question.is_approved and answer.is_approved
    assert question.created_at == datetime(2012, 8, 7, 10, 15, tzinfo=UTC)


@pytest.mark.django_db
def test_disqus_redirect_links_point_at_their_target(tmp_path):
    publication = PublicationFactory()
    html = (
        '<p><a href="http://disq.us/url?url=http%3A%2F%2Fexample.org%2Fpage%3Fa%3D1%26b%3D2%3AhashXYZ'
        '&amp;cuid=2273060" rel="nofollow">link</a></p>'
    )

    _import(tmp_path, _thread(publication, _post("10", "2012-08-07T10:00:00", html=html)), "--apply")

    assert Comment.objects.get(disqus_id="10").content == (
        '<p><a href="http://example.org/page?a=1&amp;b=2" rel="nofollow">link</a></p>'
    )


@pytest.mark.django_db
def test_deleted_comment_becomes_an_empty_placeholder_that_keeps_its_reply(tmp_path):
    publication = PublicationFactory()
    threads = _thread(
        publication,
        _post("10", "2012-08-07T10:00:00", deleted=True, html=""),
        _post("11", "2012-08-08T10:00:00", parent=10),
    )

    _import(tmp_path, threads, "--apply")

    placeholder = Comment.objects.get(disqus_id="10")
    assert (placeholder.author_name, placeholder.content, placeholder.is_approved, placeholder.is_deleted) == (
        "",
        "",
        False,
        True,
    )
    assert Comment.objects.get(disqus_id="11").parent == placeholder


@pytest.mark.django_db
def test_deleted_comments_with_nothing_shown_below_them_are_not_imported(tmp_path):
    publication = PublicationFactory()
    threads = _thread(
        publication,
        _post("10", "2012-08-07T10:00:00", deleted=True, html=""),
        _post("11", "2012-08-08T10:00:00", parent=10, deleted=True, html=""),
        _post("12", "2012-08-09T10:00:00"),
    )

    _import(tmp_path, threads, "--apply")

    assert list(Comment.objects.values_list("disqus_id", flat=True)) == ["12"]


@pytest.mark.django_db
def test_rerun_adds_nothing_and_keeps_moderation(tmp_path):
    publication = PublicationFactory()
    threads = _thread(publication, _post("10", "2012-08-07T10:00:00"))
    _import(tmp_path, threads, "--apply")
    Comment.objects.update(is_approved=False)

    _import(tmp_path, threads, "--apply")

    assert list(Comment.objects.values_list("disqus_id", "is_approved")) == [("10", False)]


@pytest.mark.django_db
def test_thread_without_a_publication_is_skipped(tmp_path):
    threads = {"1": {"identifier": "BlogPost-999999", "title": "Gone", "posts": [_post("10", "2012-08-07T10:00:00")]}}

    output = _import(tmp_path, threads, "--apply")

    assert "missing" in output
    assert not Comment.objects.exists()
