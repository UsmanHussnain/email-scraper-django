from django import template

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