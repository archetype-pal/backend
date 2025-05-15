from django.db import models


SITE_NAME = "OG(H)AM"
MODEL_DISPLAY_NAME_HISTORICAL_ITEM = "Inscription"
MODEL_DISPLAY_NAME_CURRENT_ITEM = "Current Item"
FIELD_DISPLAY_NAME_SHELFMARK = "Museum/ Register number"
APP_NAME_MANUSCRIPTS = "Objects"
MODEL_DISPLAY_NAME_CATALOGUE_NUMBER = "OG(H)AM reference"


class HISTORICAL_ITEM_TYPE(models.TextChoices):
    MONUMENT = "Monument"
    PORTABLE_OBJECT = "Portable Object"
    MANUSCRIPT = "Manuscript"


class HISTORICAL_ITEM_HAIR_TYPE(models.TextChoices):
    STONE = "Stone"
    METAL = "Metal"
    WOOD = "Wood"
    BONE_OR_ANTLER = "Bone or Antler"
    VELLUM = "Vellum"
    PAPER = "Paper"


FIELD_DISPLAY_NAME_HISTORICAL_ITEM_HAIR_TYPE = "Material Type"


class REPOSITORY_TYPE(models.TextChoices):
    MUSEUM = "Museum"
    LIBRARY = "Library"
    INSTITUTON = "Institution"
