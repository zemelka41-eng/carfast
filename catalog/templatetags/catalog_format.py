from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
from collections.abc import Mapping, Sequence

from django import template

from catalog.utils.text_cleaner import clean_text

register = template.Library()


@register.filter(name="format_rub")
def format_rub(value):
    """
    Format number as RUB with thousands separator and ₽ sign.

    - Accepts int/Decimal/float/str
    - Drops trailing .00
    - Uses non‑breaking spaces between thousands groups
    """
    if value is None:
        return ""

    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return f"{value} ₽"

    sign = "-" if d < 0 else ""
    d_abs = abs(d)

    # If fractional part is zero -> show as integer
    if d_abs == d_abs.to_integral_value():
        grouped = f"{int(d_abs):,}".replace(",", "\xa0")
        return f"{sign}{grouped} ₽"

    # Keep fractional part as-is (typically 2 decimals for prices)
    raw = format(d_abs, "f")
    if "." in raw:
        int_part, frac_part = raw.split(".", 1)
        grouped = f"{int(int_part):,}".replace(",", "\xa0")
        return f"{sign}{grouped}.{frac_part} ₽"

    grouped = f"{int(raw):,}".replace(",", "\xa0")
    return f"{sign}{grouped} ₽"


def _is_empty_option_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return True
        # Common "empty" JSON-ish strings
        if s in ("{}", "[]", "null", "None"):
            return True
        return False
    if isinstance(value, Mapping):
        return len(value) == 0
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    return False


def _parse_json_if_string(value: object) -> object:
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    if s[0] not in "{[":
        return value
    try:
        return json.loads(s)
    except Exception:
        return value


def _format_scalar(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, (int, float, Decimal)):
        try:
            d = Decimal(str(value))
            if d == d.to_integral_value():
                return str(int(d))
            return str(d.normalize())
        except Exception:
            return str(value)
    return str(value).strip()


@register.filter(name="options_to_items")
def options_to_items(value: object) -> list[dict]:
    """
    Normalize Product.options-like value (dict/list/JSON string) into template-friendly items.

    Returns a list of dicts:
    - {"type": "pair", "key": str, "value": str} for key/value options
    - {"type": "pair", "key": str, "values": [str]} for key/list options
    - {"type": "text", "value": str} for list/string options

    Empty values are filtered out; resulting empty list means "do not render options block".
    """

    value = _parse_json_if_string(value)
    if _is_empty_option_value(value):
        return []

    items: list[dict] = []

    # Dict / mapping -> key/value list
    if isinstance(value, Mapping):
        for k, v in value.items():
            key = _format_scalar(k)
            if not key:
                continue
            v = _parse_json_if_string(v)
            if _is_empty_option_value(v):
                continue

            if isinstance(v, Mapping):
                # Flatten nested mapping into a readable string
                parts: list[str] = []
                for nk, nv in v.items():
                    nk_s = _format_scalar(nk)
                    nv = _parse_json_if_string(nv)
                    if _is_empty_option_value(nv):
                        continue
                    nv_s = _format_scalar(nv)
                    if nk_s and nv_s:
                        parts.append(f"{nk_s}: {nv_s}")
                    elif nv_s:
                        parts.append(nv_s)
                if parts:
                    items.append({"type": "pair", "key": key, "value": "; ".join(parts)})
                continue

            if isinstance(v, (list, tuple)):
                if len(v) == 3 and str(v[0]).strip().lower() == "pair":
                    val_s = _format_scalar(_parse_json_if_string(v[2]))
                    if val_s:
                        items.append({"type": "pair", "key": key, "value": val_s})
                    continue
                values = [
                    _format_scalar(x)
                    for x in (_parse_json_if_string(x) for x in v)
                    if not _is_empty_option_value(x) and _format_scalar(x)
                ]
                if values:
                    items.append({"type": "pair", "key": key, "values": values})
                continue

            val_s = _format_scalar(v)
            if val_s:
                items.append({"type": "pair", "key": key, "value": val_s})

        return items

    # List / sequence -> bullet list
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        # Check if the entire value is a "pair" list: ["pair", key, value]
        if len(value) == 3 and str(value[0]).strip().lower() == "pair":
            key_s = _format_scalar(_parse_json_if_string(value[1]))
            val_s = _format_scalar(_parse_json_if_string(value[2]))
            if key_s and val_s:
                items.append({"type": "pair", "key": key_s, "value": val_s})
            return items
        
        # Parse flat sequence with "pair" markers: ["pair", key1, value1, "pair", key2, value2, ...]
        # First, check if this looks like a flat sequence with "pair" markers
        value_list = list(value)
        has_pair_markers = False
        for item in value_list:
            item_parsed = _parse_json_if_string(item)
            # Check if item is a standalone "pair" string (not part of nested list/tuple)
            if not isinstance(item_parsed, (list, tuple, Mapping)) and str(item_parsed).strip().lower() == "pair":
                has_pair_markers = True
                break
        
        if has_pair_markers:
            # Parse flat sequence with "pair" markers
            i = 0
            while i < len(value_list):
                item = value_list[i]
                item = _parse_json_if_string(item)
                item_str = str(item).strip().lower()
                
                # Check if this is a "pair" marker
                if item_str == "pair":
                    # Check if we have enough elements for a complete triplet
                    if i + 2 < len(value_list):
                        key_raw = value_list[i + 1]
                        val_raw = value_list[i + 2]
                        key_raw = _parse_json_if_string(key_raw)
                        val_raw = _parse_json_if_string(val_raw)
                        
                        key_s = _format_scalar(key_raw)
                        if not _is_empty_option_value(val_raw):
                            if isinstance(val_raw, (list, tuple)):
                                # Handle list values
                                values = [
                                    _format_scalar(x)
                                    for x in (_parse_json_if_string(x) for x in val_raw)
                                    if not _is_empty_option_value(x) and _format_scalar(x)
                                ]
                                if key_s and values:
                                    items.append({"type": "pair", "key": key_s, "values": values})
                            else:
                                val_s = _format_scalar(val_raw)
                                if key_s and val_s:
                                    items.append({"type": "pair", "key": key_s, "value": val_s})
                        i += 3
                        continue
                    else:
                        # Incomplete triplet, skip the "pair" marker
                        i += 1
                        continue
                
                # Not a "pair" marker, process normally
                if isinstance(item, (list, tuple)) and len(item) == 3 and str(item[0]).strip().lower() == "pair":
                    # Element is a triplet list: ["pair", key, value]
                    key_raw = item[1]
                    val_raw = item[2]
                    key_raw = _parse_json_if_string(key_raw)
                    val_raw = _parse_json_if_string(val_raw)
                    
                    key_s = _format_scalar(key_raw)
                    if not _is_empty_option_value(val_raw):
                        if isinstance(val_raw, (list, tuple)):
                            values = [
                                _format_scalar(x)
                                for x in (_parse_json_if_string(x) for x in val_raw)
                                if not _is_empty_option_value(x) and _format_scalar(x)
                            ]
                            if key_s and values:
                                items.append({"type": "pair", "key": key_s, "values": values})
                        else:
                            val_s = _format_scalar(val_raw)
                            if key_s and val_s:
                                items.append({"type": "pair", "key": key_s, "value": val_s})
                    i += 1
                    continue
                
                # Regular element processing
                if _is_empty_option_value(item):
                    i += 1
                    continue
                
                if isinstance(item, Mapping):
                    for k, v in item.items():
                        key = _format_scalar(k)
                        v = _parse_json_if_string(v)
                        v_s = _format_scalar(v)
                        if key and v_s:
                            items.append({"type": "text", "value": f"{key}: {v_s}"})
                    i += 1
                    continue
                
                # Skip standalone "pair" strings
                if item_str == "pair":
                    i += 1
                    continue
                
                x_s = _format_scalar(item)
                if x_s:
                    items.append({"type": "text", "value": x_s})
                i += 1
            
            return items
        
        # Regular list processing (no "pair" markers detected)
        for x in value:
            x = _parse_json_if_string(x)
            if _is_empty_option_value(x):
                continue
            if isinstance(x, (list, tuple)) and len(x) == 3 and str(x[0]).strip().lower() == "pair":
                # Element is a triplet list: ["pair", key, value]
                key_raw = x[1]
                val_raw = x[2]
                key_raw = _parse_json_if_string(key_raw)
                val_raw = _parse_json_if_string(val_raw)
                
                key_s = _format_scalar(key_raw)
                if not _is_empty_option_value(val_raw):
                    if isinstance(val_raw, (list, tuple)):
                        values = [
                            _format_scalar(v)
                            for v in (_parse_json_if_string(v) for v in val_raw)
                            if not _is_empty_option_value(v) and _format_scalar(v)
                        ]
                        if key_s and values:
                            items.append({"type": "pair", "key": key_s, "values": values})
                    else:
                        val_s = _format_scalar(val_raw)
                        if key_s and val_s:
                            items.append({"type": "pair", "key": key_s, "value": val_s})
                continue
            if isinstance(x, Mapping):
                for k, v in x.items():
                    key = _format_scalar(k)
                    v_s = _format_scalar(_parse_json_if_string(v))
                    if key and v_s:
                        items.append({"type": "text", "value": f"{key}: {v_s}"})
                continue
            # Skip standalone "pair" strings
            if str(x).strip().lower() == "pair":
                continue
            x_s = _format_scalar(x)
            if x_s:
                items.append({"type": "text", "value": x_s})
        return items

    # String / scalar -> single item
    s = _format_scalar(value)
    return [{"type": "text", "value": s}] if s else []


@register.filter(name="clean_text")
def clean_text_filter(value):
    """
    Clean text from template artifacts and placeholders.
    Use for alt/title/description fields that may contain unwanted strings.
    """
    return clean_text(value)


@register.filter(name="truncate_meta_description")
def truncate_meta_description_filter(value, max_len=155):
    """
    Truncate text for meta description: strip HTML tags, normalize whitespace,
    cut at max_len without breaking words, add ellipsis if truncated.
    Ideal length: 155-160 chars for Google snippets.
    """
    return truncate_meta_description(value, max_len)


def truncate_meta_description(text, max_len=155):
    """
    Utility function for truncating meta description.
    - Strip HTML tags
    - Normalize whitespace
    - Cut at word boundary
    - Add ellipsis if truncated
    """
    import re
    from django.utils.html import strip_tags
    
    if not text:
        return ""
    
    # Strip HTML tags and normalize whitespace
    text = strip_tags(str(text))
    text = re.sub(r'\s+', ' ', text).strip()
    
    if len(text) <= max_len:
        return text
    
    # Cut at word boundary
    truncated = text[:max_len]
    # Find last space to avoid cutting mid-word
    last_space = truncated.rfind(' ')
    if last_space > max_len - 30:  # If space is reasonably close to end
        truncated = truncated[:last_space]
    
    return truncated.rstrip('.,;:!? ') + '…'




@register.filter(name="splitlines")
def splitlines_filter(value: object) -> list[str]:
    if value is None:
        return []
    lines: list[str] = []
    for line in str(value).splitlines():
        item = line.strip()
        if item:
            lines.append(item)
    return lines

