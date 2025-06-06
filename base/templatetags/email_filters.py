from django import template
import re
register = template.Library()

@register.filter
def dictsortreversed(value, field_name):
    """
    Sort a list of dictionaries by the specified field in descending order.
    """
    return sorted(value, key=lambda x: getattr(x, field_name), reverse=True)

@register.filter
def select_by_email(messages, email):
    """
    Filter messages to include only those related to the given email.
    """
    return [msg for msg in messages if msg.sender == email or msg.receiver == email]

@register.filter
def filter_unread(messages):
    """
    Filter messages to include only unread messages that were not sent by the user.
    """
    return [msg for msg in messages if not msg.is_read and not msg.is_sent]

@register.filter
def normalize_spacing(value):
    """Normalize HTML spacing by replacing double breaks with single and removing excessive spaces."""
    if not value:
        return value
    # Replace double <br> or <p> with single <br>
    value = re.sub(r'<br>\s*<br>|<p>\s*</p>|<p>\s*(?:<br>)?\s*</p>', '<br>', value)
    # Replace multiple newlines with single newline
    value = re.sub(r'\n\s*\n+', '\n', value)
    # Replace multiple spaces with single space
    value = re.sub(r'\s{2,}', ' ', value)
    return value.strip()