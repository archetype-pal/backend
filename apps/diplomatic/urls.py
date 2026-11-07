from django.urls import path
from rest_framework import routers

from .views import (
    CharterEntityViewSet,
    DiplomaticSummaryView,
    FormulaViewSet,
    NetworkExportView,
    NetworkView,
    ProposalManagementViewSet,
    RelationViewSet,
)

router = routers.SimpleRouter()

router.register("management/diplomatic-proposals", ProposalManagementViewSet, basename="diplomatic-proposals")
router.register("diplomatic/entities", CharterEntityViewSet, basename="diplomatic-entities")
router.register("diplomatic/formulae", FormulaViewSet, basename="diplomatic-formulae")
router.register("diplomatic/relations", RelationViewSet, basename="diplomatic-relations")

urlpatterns = [
    path("diplomatic/summary/", DiplomaticSummaryView.as_view(), name="diplomatic-summary"),
    path("diplomatic/network/", NetworkView.as_view(), name="diplomatic-network"),
    path("diplomatic/network/gexf/", NetworkExportView.as_view(), name="diplomatic-network-gexf"),
    *router.urls,
]
