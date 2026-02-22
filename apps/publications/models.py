from admin_ordering.models import OrderableModel
from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator
from django.db import models
import tagulous.models
from tinymce.models import HTMLField

User = get_user_model()


class CarouselItem(OrderableModel):
    image = models.ImageField(upload_to="carousel", help_text="The image for this item")
    title = models.CharField(
        max_length=150, help_text="The caption under the image of this item. This can contain some inline HTML."
    )
    url = models.CharField(
        max_length=200,
        blank=True,
        validators=[RegexValidator(r"^(https?://.+|/.*)$", "Enter a full URL or a relative path starting with /.")],
        help_text="Full URL or relative path (e.g. /about).",
    )

    def __str__(self):
        return self.title


class Event(models.Model):
    title = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150, unique=True)
    content = HTMLField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ["-created_at"]


class Publication(models.Model):
    class Status(models.TextChoices):
        DRAFT = "Draft"
        PUBLISHED = "Published"

    title = models.CharField(max_length=350)
    slug = models.SlugField(max_length=150, unique=True)
    content = HTMLField()
    preview = HTMLField()

    author = models.ForeignKey(User, on_delete=models.CASCADE)

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        help_text="With Draft chosen, will only be shown for admin users on the site.",
    )
    keywords = tagulous.models.TagField(force_lowercase=True, max_count=10, blank=True)
    is_blog_post = models.BooleanField(default=False)
    is_news = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    allow_comments = models.BooleanField(default=True)
    similar_posts = models.ManyToManyField("self", blank=True)
    published_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ["-created_at"]


class Comment(models.Model):
    post = models.ForeignKey(Publication, on_delete=models.CASCADE, related_name="comments")
    content = models.TextField()

    author_name = models.CharField(max_length=150)
    author_email = models.EmailField()
    author_website = models.URLField(blank=True, null=True)

    is_approved = models.BooleanField(default=False, help_text="Show on website?")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.author_name} -> {self.post.title}"

    class Meta:
        ordering = ["-created_at"]
