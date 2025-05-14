from django.db import models


SITE_NAME = "Archetype"
MODEL_DISPLAY_NAME_HISTORICAL_ITEM = "Historical Item"
MODEL_DISPLAY_NAME_CURRENT_ITEM = "Current Item"
FIELD_DISPLAY_NAME_SHELFMARK = "Shelfmark"
APP_NAME_MANUSCRIPTS = "Manuscripts"
MODEL_DISPLAY_NAME_CATALOGUE_NUMBER = "Catalogue Number"


class HISTORICAL_ITEM_TYPE(models.TextChoices):
    AGREEMENT = "Agreement"
    CHARTER = "Charter"
    LETTER = "Letter"


class HISTORICAL_ITEM_HAIR_TYPE(models.TextChoices):
    FHFH = "FHFH", "FHFH"
    FHHF = "FHHF", "FHHF"
    HFFH = "HFFH", "HFFH"
    HFHF = "HFHF", "HFHF"
    MIXED = "Mixed", "Mixed"


FIELD_DISPLAY_NAME_HISTORICAL_ITEM_HAIR_TYPE = "Hair Type"


class REPOSITORY_TYPE(models.TextChoices):
    LIBRARY = "Library"
    INSTITUTION = "Institution"
    PERSON = "Person"
    ONLINE_RESOURCE = "Online Resource"
