"""The contact form and the post notification, where they failed loudly."""

from unittest import mock

from django.core import mail
from django.test import TestCase

from core.models import User
from games import utils
from games.forms import ContactForm
from games.models import Post


def contact_form(**overrides):
    data = {"name": "Ada", "category": "general", "message": "Hello"}
    data.update(overrides)
    return ContactForm(data=data)


class ContactFormTests(TestCase):
    def test_a_name_is_put_on_one_line(self):
        form = contact_form(name="Ada\r\nBcc: someone@example.com")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["name"], "Ada Bcc: someone@example.com")

    def test_a_name_with_a_line_break_still_sends(self):
        """It was a `BadHeaderError`: "could not be sent", and an ERROR."""
        form = contact_form(name="Ada\nLovelace")
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertNoLogs(utils.logger, level="ERROR"):
            sent = utils.send_contact_email(
                form.cleaned_data["name"],
                "",
                form.cleaned_data["category"],
                form.cleaned_data["message"],
            )
        self.assertTrue(sent)
        self.assertIn("from Ada Lovelace", mail.outbox[0].subject)

    def test_a_name_of_only_line_breaks_is_no_name(self):
        self.assertIn("name", contact_form(name="\n\r\n").errors)

    def test_a_message_has_a_ceiling(self):
        self.assertTrue(contact_form(message="a" * 10000).is_valid())
        self.assertIn("message", contact_form(message="a" * 10001).errors)


class PostNotificationTests(TestCase):
    def subscriber(self, name="subscriber"):
        user = User.objects.create_user(
            username=name, email=f"{name}@example.com", email_subscribed=True
        )
        user.generate_unsubscribe_token()
        user.save()
        return user

    def test_a_post_the_email_cannot_be_built_from_is_a_failed_send(self):
        """Building it was outside the `try`: the exception left the
        notification thread, and the rest of the subscribers unsent."""
        post = Post.objects.create(title="News", text="Body")
        post.date = None  # nothing to format
        with self.assertLogs(utils.logger, level="ERROR") as logs:
            sent = utils.send_post_notification_email(post, self.subscriber())
        self.assertFalse(sent)
        self.assertEqual(mail.outbox, [])
        self.assertIn("Failed to send post notification email", logs.output[0])

    def test_one_subscriber_failing_does_not_stop_the_rest(self):
        post = Post.objects.create(title="News", text="Body")
        first, second = self.subscriber("first"), self.subscriber("second")
        real = utils._post_notification_email

        def build(post, user):
            if user == first:
                raise ValueError("cannot build")
            return real(post, user)

        with (
            mock.patch.object(utils, "_post_notification_email", build),
            self.assertLogs(utils.logger, level="ERROR"),
        ):
            results = [
                utils.send_post_notification_email(post, user)
                for user in (first, second)
            ]
        self.assertEqual(results, [False, True])
        self.assertEqual(mail.outbox[0].to, [second.email])

    def test_the_title_is_text_in_the_html_part(self):
        """The post's body is rendered markdown, HTML by design; the title
        is a line of text, and went into the page as written."""
        post = Post.objects.create(title="Q&A <2026>", text="Body")
        self.assertTrue(utils.send_post_notification_email(post, self.subscriber()))
        message = mail.outbox[0]
        html_part = message.alternatives[0][0]
        self.assertIn("Q&amp;A &lt;2026&gt;</h2>", html_part)
        self.assertIn("Q&A <2026>", message.body)
        self.assertEqual(message.subject, "Q&A <2026>")

    def test_the_email_carries_a_one_click_unsubscribe(self):
        """A mail client's own control, which POSTs: the link itself only
        asks, since a scanner follows every link in a message."""
        post = Post.objects.create(title="News", text="Body")
        subscriber = self.subscriber()
        self.assertTrue(utils.send_post_notification_email(post, subscriber))

        headers = mail.outbox[0].extra_headers
        link = headers["List-Unsubscribe"]
        self.assertTrue(link.startswith("<") and link.endswith(">"))
        self.assertTrue(
            link[1:-1].endswith(f"/unsubscribe/{subscriber.unsubscribe_token}/")
        )
        self.assertEqual(headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        # The address the header names is one the view answers a POST at
        path = "/unsubscribe/" + link[1:-1].split("/unsubscribe/", 1)[1]
        self.assertEqual(self.client.post(path).status_code, 200)
        subscriber.refresh_from_db()
        self.assertFalse(subscriber.email_subscribed)
