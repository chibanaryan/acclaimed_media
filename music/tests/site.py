"""
Run music tests against the music site's URLconf.

music.acclaimedmedia.org has a URLconf of its own (``settings.SITE_URLCONFS``),
while the test client's ``testserver`` host gets ``ROOT_URLCONF``, the games
site's. A module of music tests imports the module fixtures, so its requests
and its ``reverse()`` calls are on the music site throughout::

    from music.tests.site import setUpModule, tearDownModule  # noqa: F401

Both runners call them, Django's and pytest's. A music test class in a module
that is mostly about games takes the decorator instead::

    @music_site
    class AlbumPageTests(TestCase): ...
"""

from django.conf import settings
from django.test import override_settings

music_site = override_settings(ROOT_URLCONF=settings.SITE_URLCONFS["music"])
_module_override = override_settings(ROOT_URLCONF=settings.SITE_URLCONFS["music"])


def setUpModule():
    _module_override.enable()


def tearDownModule():
    _module_override.disable()
