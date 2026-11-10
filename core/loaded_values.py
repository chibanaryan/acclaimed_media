"""What a row held when it was read, kept on the instance at no query.

A cache keyed on a value has to be dropped when that value changes, and a
``post_save`` sees only the new one. Reading the old one back in ``pre_save``
is a query on every save, and the metadata passes save every game and album.
A model that takes ``RemembersLoaded`` keeps the values of its
``remembered_fields`` as the database last gave or took them, so a signal
can ask ``previous(instance, "year_released")``.
"""

# No value is known: the field was deferred, or the instance was built by
# hand and never read or saved
UNKNOWN = object()


def remember(instance, only=None) -> None:
    """Note the remembered fields as they stand, which is as the row has them.

    ``only`` names the fields a save wrote (its ``update_fields``): the
    others are still in the row as they were.
    """
    values = instance.__dict__.setdefault("_loaded_values", {})
    for name in instance.remembered_fields:
        if only is None or name in only:
            values[name] = instance.__dict__.get(name, UNKNOWN)


def previous(instance, name, update_fields=None):
    """The value ``name`` had in the row if a save has changed it, else ``UNKNOWN``.

    ``UNKNOWN`` too when the old value was never known, so a caller acts only
    on a change it can see, and when the save named its ``update_fields``
    and left this one out: the row still holds the old value then.
    """
    if update_fields is not None and name not in update_fields:
        return UNKNOWN
    old = getattr(instance, "_loaded_values", {}).get(name, UNKNOWN)
    if old is UNKNOWN or old == getattr(instance, name):
        return UNKNOWN
    return old


def changed(instance, name, update_fields=None) -> bool:
    """True if a save is known to have changed ``name`` in the row."""
    return previous(instance, name, update_fields) is not UNKNOWN


class RemembersLoaded:
    """Model mixin: remember ``remembered_fields`` on load and after a save.

    Listed before the model base, so ``from_db`` and ``save`` reach it first.
    """

    remembered_fields: tuple = ()

    @classmethod
    def from_db(cls, db, field_names, values, **kwargs):
        # Whatever else Django passes (6.1's `fetch_mode`) goes on to it:
        # without the keyword it takes a deprecated path and the queryset's
        # fetch mode is dropped
        instance = super().from_db(db, field_names, values, **kwargs)
        remember(instance)
        return instance

    def save(self, *args, **kwargs):
        # After the save and its signals, which are what ask
        super().save(*args, **kwargs)
        remember(self, only=kwargs.get("update_fields"))
