from django.urls import path

from .views import (
    LearnStatusView,
    QuestionsView,
    SessionPictureView,
    SessionsView,
    SessionView,
    SuggestedPagesView,
)

urlpatterns = [
    path("learn/", LearnStatusView.as_view(), name="learn-status"),
    path("learn/pages/", SuggestedPagesView.as_view(), name="learn-pages"),
    path("learn/sessions/", SessionsView.as_view(), name="learn-sessions"),
    path("learn/sessions/<str:pk>/", SessionView.as_view(), name="learn-session"),
    path("learn/sessions/<str:pk>/picture/", SessionPictureView.as_view(), name="learn-session-picture"),
    path("learn/sessions/<str:pk>/questions/", QuestionsView.as_view(), name="learn-session-questions"),
]
