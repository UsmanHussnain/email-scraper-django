from django import template
from urllib.parse import urlencode, parse_qs, urlparse

register = template.Library()

@register.filter
def removeparam(value, param):
    parsed = urlparse('?' + value)
    query_dict = parse_qs(parsed.query)
    query_dict.pop(param, None)
    return urlencode(query_dict, doseq=True)