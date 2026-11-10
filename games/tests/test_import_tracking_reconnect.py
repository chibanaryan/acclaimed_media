"""A games import reconnects readers' rows without a query for every game."""

from io import StringIO
from unittest import mock

from django.test import TestCase

from core.models import User
from games import models, utils

RECONNECT = "games.services.user_tracking_service.reconnect_tracking_records"


def release(*rows):
    return StringIO("".join(f"{row}\r\n" for row in rows))


class ReconnectOnlyWhatIsTrackedTests(TestCase):
    ROWS = (
        "1\tAlpha\t2000\tPC\t101\tQ1",
        "2\tBeta\t2001\tPC\t102,202\tQ2",
        "3\tGamma\t2002\tPC\t103\tQ3",
    )

    def setUp(self):
        self.reader = User.objects.create_user(username="reader", password="pw")

    def test_no_tracking_rows_means_no_reconnect_at_all(self):
        """It ran, with two locking queries, for every game in the file."""
        with mock.patch(RECONNECT) as reconnect:
            success, _ = utils.import_games(release(*self.ROWS))
        self.assertTrue(success)
        reconnect.assert_not_called()

    def test_only_the_game_a_row_names_is_reconnected(self):
        models.PlayedGame.objects.create(user=self.reader, igdb_id=101)
        with mock.patch(RECONNECT) as reconnect:
            utils.import_games(release(*self.ROWS))
        self.assertEqual(
            [call.kwargs["primary_igdb_id"] for call in reconnect.call_args_list],
            [101],
        )

    def test_a_row_under_a_secondary_id_still_reconnects(self):
        played = models.PlayedGame.objects.create(user=self.reader, igdb_id=202)
        want = models.WantToPlayGame.objects.create(user=self.reader, igdb_id=103)

        utils.import_games(release(*self.ROWS))

        played.refresh_from_db()
        want.refresh_from_db()
        self.assertEqual((played.game.name, played.igdb_id), ("Beta", 102))
        self.assertEqual(want.game.name, "Gamma")

    def test_a_row_for_a_game_the_release_drops_stays_orphaned(self):
        played = models.PlayedGame.objects.create(user=self.reader, igdb_id=999)
        utils.import_games(release(*self.ROWS))
        played.refresh_from_db()
        self.assertIsNone(played.game)
