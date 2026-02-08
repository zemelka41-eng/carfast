from django import template
from carfst_site.build_id import get_build_id as _get_build_id

register = template.Library()


@register.simple_tag
def get_build_id():
    """Return BUILD_ID for display in templates."""
    return _get_build_id()
