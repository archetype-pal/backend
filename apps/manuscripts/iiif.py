from urllib.parse import urljoin

from django.conf import settings


def get_iiif_url(file_path: str, profile_name: str | None = None) -> str:
    """
    Helper function to join parts of a URL for IIIF.
    """
    profile_name = profile_name or list(settings.IIIF_PROFILES.keys())[0]

    iiif_profile = settings.IIIF_PROFILES.get(profile_name, None)
    if not iiif_profile:
        raise ValueError(f"Profile '{profile_name}' not found in IIIF_PROFILES.")
    iiif_path = file_path.replace("/", "%2F")
    iiif_path += f"/{iiif_profile['region']}/{iiif_profile['size']}/{iiif_profile['rotation']}"
    iiif_path += f"/{iiif_profile['quality']}.{iiif_profile['format']}"
    return urljoin(iiif_profile["host"], iiif_path)
