import re
from datetime import datetime

from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def score_tone(score):
    """Return a visual tone for a score such as 8/10 or 80%."""
    if not score or score == "-":
        return "score-none"
    match = re.fullmatch(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", str(score))
    if match:
        earned, maximum = (float(value) for value in match.groups())
        percentage = earned / maximum * 100 if maximum else 0
    else:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)%", str(score))
        if not match:
            return "score-none"
        percentage = float(match.group(1))

    if percentage >= 100:
        return "score-good"
    if percentage > 0:
        return "score-partial"
    return "score-zero"


@register.filter
def total_tone(total):
    if not total:
        return "score-none"
    percentage = float(total.get("adjusted_percentage", 0))
    if percentage >= 100:
        return "score-good"
    if percentage > 0:
        return "score-partial"
    return "score-zero"


@register.filter
def submission_tone(row):
    if row.get("status") in {"no_runs", "error"}:
        return "submission-missing"
    if row.get("late_penalty", 0) < 0:
        return "submission-late"
    return "submission-on-time"


@register.filter
def local_time(value):
    """Convert an ISO timestamp to the site's configured local timezone."""
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return value
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.utc)
    return (
        timezone.localtime(parsed).strftime("%b %d, %Y - %I:%M %p").replace(" 0", " ")
    )
