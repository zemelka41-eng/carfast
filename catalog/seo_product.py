"""
Unified SEO generator for product cards (product_detail).
Covers long-tail: type + SHACMAN + model_variant + wheel_formula + model_code + engine.
"""
from catalog.models import Product
from catalog.utils.text_cleaner import clean_text


def _extract_option_value(options: object, key_part: str) -> str:
    if not isinstance(options, dict):
        return ""
    for k, v in options.items():
        if key_part not in str(k).lower():
            continue
        if isinstance(v, (list, tuple)):
            if len(v) == 3 and str(v[0]).strip().lower() == "pair":
                return str(v[2]).strip()
            return ", ".join(str(item).strip() for item in v if str(item).strip())
        return str(v).strip()
    return ""


def build_product_seo_title(product: Product) -> str:
    """
    Title: Купить + type + SHACMAN + 2–3 tech (формула, двигатель/модель, тоннаж)
    + CTR: цена, в наличии, лизинг, доставка (only if true). Unique per product.
    """
    if getattr(product, "seo_title_override", None) and (product.seo_title_override or "").strip():
        return (product.seo_title_override or "").strip()

    base = product.model_name_ru or product.sku or "Техника"
    parts = [base]
    if product.wheel_formula:
        parts.append(product.wheel_formula)
    engine = product.engine_model or _extract_option_value(getattr(product, "options", None) or {}, "двиг")
    if engine:
        parts.append(engine)
    cabin = _extract_option_value(getattr(product, "options", None) or {}, "кабин")
    if cabin and cabin not in (parts[-1] if parts else ""):
        parts.append(cabin)
    # Keep at most 2–3 tech attributes after model name
    tech = parts[1:4]
    title = f"Купить {base}"
    if tech:
        title += " — " + ", ".join(tech)
    title += " Shacman"

    total_qty = getattr(product, "total_qty", 0) or 0
    has_price = getattr(product, "display_price", None) is not None or (product.price is not None)
    if total_qty and has_price:
        title += " — цена, в наличии"
    elif total_qty:
        title += " — в наличии"
    elif has_price:
        title += " — цена под заказ"
    title += ". Лизинг, доставка | CARFAST"
    return title[:255] if len(title) > 255 else title


def build_product_seo_description(product: Product) -> str:
    """
    Meta description: 2–3 tech (формула, двигатель, модель) + Shacman + CTR: цена, в наличии, лизинг, доставка, КП.
    """
    if getattr(product, "seo_description_override", None) and (product.seo_description_override or "").strip():
        raw = (product.seo_description_override or "").strip()
        return raw[:157].rstrip() + "..." if len(raw) > 160 else raw

    base = product.model_name_ru or product.sku
    desc = product.short_description_ru or ""
    if not desc and product.description_ru:
        desc = (product.description_ru or "")[:160]
    if not desc:
        parts = [base]
        if product.wheel_formula:
            parts.append(f"колёсная формула {product.wheel_formula}")
        engine = product.engine_model or _extract_option_value(getattr(product, "options", None) or {}, "двиг")
        if engine:
            parts.append(f"двигатель {engine}")
        parts.append("Shacman")
        desc = ". ".join(parts) + ". Цена, в наличии и под заказ. Лизинг, доставка по РФ. Запросите КП."
    if len(desc) > 160:
        desc = desc[:157].rstrip() + "..."
    return desc


def build_product_h1(product: Product) -> str:
    """H1: clean model name only (no "купить/цена")."""
    return clean_text(product.model_name_ru or product.sku or "Техника")


def build_product_first_block(product: Product) -> str:
    """
    First visible text block: SHACMAN + model/series + wheel_formula + model_code
    + 2–4 key specs + purchase conditions (лизинг/доставка).
    """
    if getattr(product, "seo_text_override", None) and (product.seo_text_override or "").strip():
        return (product.seo_text_override or "").strip()

    brand = "SHACMAN"
    model_name = product.model_name_ru or product.sku
    line = ""
    if product.model_variant:
        line = product.model_variant.line or product.model_variant.name or ""
    wf = product.wheel_formula or ""
    code = (product.model_code or "").strip()
    engine = product.engine_model or _extract_option_value(getattr(product, "options", None) or {}, "двиг")
    cabin = _extract_option_value(getattr(product, "options", None) or {}, "кабин")

    bits = [f"{brand} {model_name}"]
    if line:
        bits.append(line)
    if wf:
        bits.append(f"колёсная формула {wf}")
    if code:
        bits.append(code)
    if engine:
        bits.append(f"двигатель {engine}")
    if cabin:
        bits.append(f"кабина {cabin}")

    sentence = ". ".join(bits) + "."
    sentence += " Лизинг, доставка по РФ, гарантия. Получить коммерческое предложение — на странице или по контактам."
    return sentence


def build_product_image_alt(product: Product, suffix: str = "") -> str:
    """ALT: {тип} SHACMAN {серия} {формула} {код} (no spam)."""
    tipo = (product.model_name_ru or product.sku or "Техника").strip()
    brand = "SHACMAN" if product.series and (product.series.slug or "").lower() == "shacman" else (product.series.name if product.series else "Техника").strip()
    line = ""
    if product.model_variant:
        line = (product.model_variant.line or product.model_variant.name or "").strip()
    wf = (product.wheel_formula or "").strip()
    code = (product.model_code or "").strip()
    parts = [tipo, brand]
    if line:
        parts.append(line)
    if wf:
        parts.append(wf)
    if code:
        parts.append(code)
    if suffix:
        parts.append(suffix)
    return " ".join(parts).strip()
