"""Index type value object: named searchable collection."""

from enum import Enum


class IndexType(str, Enum):
    """Named searchable collection. URL segment uses hyphenated form (e.g. item-parts)."""

    ITEM_PARTS = "item_parts"
    ITEM_IMAGES = "item_images"
    SCRIBES = "scribes"
    HANDS = "hands"
    GRAPHS = "graphs"

    @property
    def uid(self) -> str:
        """Meilisearch index UID (no prefix)."""
        return self.value

    @classmethod
    def from_url_segment(cls, segment: str) -> "IndexType | None":
        """Parse URL path segment (e.g. 'item-parts') to IndexType."""
        mapping = {
            "item-parts": cls.ITEM_PARTS,
            "item-images": cls.ITEM_IMAGES,
            "scribes": cls.SCRIBES,
            "hands": cls.HANDS,
            "graphs": cls.GRAPHS,
        }
        return mapping.get(segment)

    def to_url_segment(self) -> str:
        """URL path segment for this index type."""
        mapping = {
            type(self).ITEM_PARTS: "item-parts",
            type(self).ITEM_IMAGES: "item-images",
            type(self).SCRIBES: "scribes",
            type(self).HANDS: "hands",
            type(self).GRAPHS: "graphs",
        }
        return mapping[self]
