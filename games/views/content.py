"""Static and editorial pages: contact, flat pages, the blog, 404, robots.txt."""

import html
import logging

from django.conf import settings
from django.contrib.flatpages.models import FlatPage
from django.http import HttpResponse, HttpResponseGone
from django.shortcuts import redirect, get_object_or_404
from django.utils.html import strip_tags
from django.utils.text import Truncator
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, TemplateView, FormView

from core.mixins import HTMXPartialMixin, RobustPaginationMixin
from core.models import User
from core.services.client_ip import get_client_ip
from games import models, utils
from games.forms import ContactForm
from games.services import contact_spam_guard

logger = logging.getLogger(__name__)


class ContactFormView(FormView):
    """Dedicated contact form handler (for form POST from modal)."""

    form_class = ContactForm
    success_url = reverse_lazy("contact_thank_you")
    template_name = "contact.html"  # Minimal template for form errors

    def form_valid(self, form):
        """Process valid contact form submission and send email."""
        name = form.cleaned_data["name"]
        email = form.cleaned_data["email"]
        category = form.cleaned_data["category"]
        message = form.cleaned_data["message"]

        decision = contact_spam_guard.evaluate(self.request, form.cleaned_data)
        if not decision.allowed:
            logger.warning(
                "Contact submission blocked (reason=%s ip=%s category=%s)",
                decision.reason,
                decision.client_ip,
                category,
            )
            return redirect(self.success_url)

        # Send the email
        email_sent = utils.send_contact_email(name, email, category, message)

        if not email_sent:
            form.add_error(
                None,
                "We're sorry, but there was an error sending your message. "
                "Please try again later or email us directly at "
                "contact@acclaimedvideogames.com",
            )
            return self.form_invalid(form)

        return super().form_valid(form)

    def form_invalid(self, form):
        """Handle invalid submissions, silently dropping honeypot spam."""
        if self._honeypot_only_error(form):
            client_ip = get_client_ip(self.request)
            category = self.request.POST.get("category", "")
            logger.warning(
                "Contact submission blocked (reason=honeypot ip=%s category=%s)",
                client_ip,
                category,
            )
            return redirect(self.success_url)
        return super().form_invalid(form)

    @staticmethod
    def _honeypot_only_error(form):
        error_fields = set(form.errors.keys())
        return error_fields == {"website"}


class ContactThankYouView(TemplateView):
    """Display thank you page after successful contact form submission."""

    template_name = "contact_thank_you.html"


class PageDetailView(TemplateView):
    template_name = "pages/page_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import markdown

        slug = kwargs.get("slug")
        # Try /page/{slug}/ first (for consistency with URL pattern), then /{slug}/
        try:
            flatpage = FlatPage.objects.get(url=f"/page/{slug}/")
        except FlatPage.DoesNotExist:
            # Fall back to /{slug}/ format (matches existing database entries)
            flatpage = get_object_or_404(FlatPage, url=f"/{slug}/")

        # Convert markdown to HTML (matching API serializer behavior)
        if flatpage.content:
            flatpage.rendered_content = markdown.markdown(flatpage.content)
        else:
            flatpage.rendered_content = ""
        # Plain text for the meta description: striptags in the template
        # left markdown's entities in place and autoescape escaped them again
        # ("Q&A" became "Q&amp;A" in search results)
        flatpage.meta_description = Truncator(
            html.unescape(strip_tags(flatpage.rendered_content)).strip()
        ).chars(155)

        context["flatpage"] = flatpage
        return context


def news_gone(request):
    """The public /news/ page was removed; 410 tells search engines to deindex it."""
    return HttpResponseGone()


class ArticleListView(RobustPaginationMixin, HTMXPartialMixin, ListView):
    """Blog article list with pagination."""

    model = models.Article
    template_name = "articles/article_list.html"
    context_object_name = "articles"
    paginate_by = 10
    paginate_orphans = 0
    htmx_partial_template = "articles/includes/_article_list_content.html"

    def get_queryset(self):
        return (
            models.Article.objects.filter(status=models.Article.Status.PUBLISHED)
            .select_related("author")
            .order_by("-published_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        page_obj = context.get("page_obj")
        if page_obj:
            context["total_count"] = page_obj.paginator.count
            context["loaded_count"] = page_obj.end_index()
        return context


class ArticleDetailView(DetailView):
    """Individual article detail page."""

    model = models.Article
    template_name = "articles/article_detail.html"
    context_object_name = "article"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        qs = models.Article.objects.select_related("author")
        # Staff can preview drafts
        if self.request.user.is_staff:
            return qs
        return qs.filter(status=models.Article.Status.PUBLISHED)


class NotFoundView(TemplateView):
    """
    Custom 404 page with auto-redirect.
    """

    template_name = "404.html"

    def dispatch(self, request, *args, **kwargs):
        # Handle all HTTP methods (GET, POST, etc.) the same way
        context = self.get_context_data(**kwargs)
        response = self.render_to_response(context)
        response.status_code = 404
        return response


def custom_404_view(request, exception):
    """
    Function-based wrapper for NotFoundView (required for handler404).
    """
    return NotFoundView.as_view()(request, exception=exception)


def robots_txt(request):
    """
    Serve robots.txt for search engine crawlers.

    Blocks aggressive/low-value crawlers and disallows expensive filtered
    query patterns that can overwhelm the server.

    The music rules appear only once ``MUSIC_ENABLED`` is on: robots.txt is
    public, so naming the hidden section's paths would advertise it.
    """
    music_rules = (
        "Disallow: /music/import/\nDisallow: /music/download/\n"
        if settings.MUSIC_ENABLED
        else ""
    )
    content = f"""\
# Aggressive/low-value crawlers - block entirely
User-agent: AhrefsBot
Disallow: /

User-agent: SemrushBot
Disallow: /

User-agent: MJ12bot
Disallow: /

User-agent: DotBot
Disallow: /

User-agent: BLEXBot
Disallow: /

User-agent: PetalBot
Disallow: /

User-agent: BaiduSpider
Disallow: /

# All other crawlers
User-agent: *
Allow: /
Crawl-delay: 10
Disallow: /admin/
Disallow: /import/
Disallow: /api/
Disallow: /download/
{music_rules}Disallow: /*?*start=
Disallow: /*?*end=
Disallow: /*?*highlight=
Disallow: /*?*page=

Sitemap: {settings.CANONICAL_ORIGIN}/sitemap.xml
"""
    return HttpResponse(content, content_type="text/plain")


class UnsubscribeView(TemplateView):
    """Handle unsubscribe requests."""

    template_name = "unsubscribe.html"

    def get(self, request, token):  # pragma: no cover
        """Process unsubscribe token."""
        try:
            user = User.objects.get(unsubscribe_token=token)
            user.email_subscribed = False
            user.save()
            return self.render_to_response({"success": True, "email": user.email})
        except User.DoesNotExist:
            return self.render_to_response({"success": False})
