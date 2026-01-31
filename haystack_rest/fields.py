from rest_framework import fields


class HaystackFieldMixin:
    """Mixin for Haystack serializer fields (source/bind for index fields)."""

    prefix_field_names = False

    def __init__(self, **kwargs):
        self.prefix_field_names = kwargs.pop("prefix_field_names", False)
        super().__init__(**kwargs)

    def bind(self, field_name, parent):
        """Set field_name and parent; default source from field name."""
        assert self.source != field_name, (
            f"It is redundant to specify `source='{field_name}'` on field '{self.__class__.__name__}' in "
            f"serializer '{parent.__class__.__name__}'. Remove the `source` keyword argument."
        )
        self.field_name = field_name
        self.parent = parent
        if self.label is None:
            self.label = field_name.replace("_", " ").capitalize()
        if self.source is None:
            self.source = self.convert_field_name(field_name)
        self.source_attrs = [] if self.source == "*" else self.source.split(".")

    def convert_field_name(self, field_name):
        return field_name if not self.prefix_field_names else field_name.split("__")[-1]


class HaystackBooleanField(HaystackFieldMixin, fields.BooleanField):
    pass


class HaystackCharField(HaystackFieldMixin, fields.CharField):
    pass


class HaystackDateField(HaystackFieldMixin, fields.DateField):
    pass


class HaystackDateTimeField(HaystackFieldMixin, fields.DateTimeField):
    pass


class HaystackDecimalField(HaystackFieldMixin, fields.DecimalField):
    pass


class HaystackFloatField(HaystackFieldMixin, fields.FloatField):
    pass


class HaystackIntegerField(HaystackFieldMixin, fields.IntegerField):
    pass


class HaystackMultiValueField(HaystackFieldMixin, fields.ListField):
    pass


class FacetDictField(fields.DictField):
    """DictField that passes the key into each child's to_representation."""

    def to_representation(self, value):
        return {str(key): self.child.to_representation(key, val) for key, val in value.items()}


class FacetListField(fields.ListField):
    """ListField that passes the parent key to each child's to_representation."""

    def to_representation(self, key, data):
        return [self.child.to_representation(key, item) for item in data]
