from rest_framework import routers

from .views import CharterEntityViewSet, FormulaViewSet, ProposalManagementViewSet, RelationViewSet

router = routers.DefaultRouter()

router.register("management/diplomatic-proposals", ProposalManagementViewSet, basename="diplomatic-proposals")
router.register("diplomatic/entities", CharterEntityViewSet, basename="diplomatic-entities")
router.register("diplomatic/formulae", FormulaViewSet, basename="diplomatic-formulae")
router.register("diplomatic/relations", RelationViewSet, basename="diplomatic-relations")

urlpatterns = router.urls
