import json
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


def get_iiif_region_from_geojson(coordinates_json: str) -> str:
    """
    Extract bounding box from GeoJSON coordinates and convert to IIIF region format.

    Args:
        coordinates_json: JSON string containing GeoJSON Feature with Polygon geometry

    Returns:
        IIIF region string in format "x,y,w,h"
    """
    try:
        if isinstance(coordinates_json, str):
            coords_data = json.loads(coordinates_json)
        else:
            coords_data = coordinates_json

        # Handle both Feature and direct geometry formats
        if coords_data.get("type") == "Feature":
            geometry = coords_data.get("geometry", {})
        else:
            geometry = coords_data

        if geometry.get("type") != "Polygon":
            return "full"

        # Get the first ring of the polygon (outer ring)
        polygon_coords = geometry.get("coordinates", [])
        if not polygon_coords or not polygon_coords[0]:
            return "full"

        ring = polygon_coords[0]

        # Extract x and y coordinates
        x_coords = [point[0] for point in ring]
        y_coords = [point[1] for point in ring]

        # Calculate bounding box
        min_x = min(x_coords)
        min_y = min(y_coords)
        max_x = max(x_coords)
        max_y = max(y_coords)

        # Calculate width and height
        width = max_x - min_x
        height = max_y - min_y

        # Convert to integers (IIIF typically uses integer coordinates)
        x = int(min_x)
        y = int(min_y)
        w = int(width)
        h = int(height)

        return f"{x},{y},{w},{h}"
    except json.JSONDecodeError, KeyError, IndexError, ValueError, TypeError:
        # If parsing fails, return "full" to show the entire image
        return "full"


def get_iiif_cropped_url(
    file_path: str,
    coordinates_json: str,
    size: str = "150,",
    rotation: str = "0",
    quality: str = "default",
    format: str = "jpg",
) -> str:
    region = get_iiif_region_from_geojson(coordinates_json)

    iiif_path = file_path.replace("/", "%2F")
    iiif_path += f"/{region}/{size}/{rotation}/{quality}.{format}"

    return urljoin(settings.IIIF_HOST, iiif_path)
