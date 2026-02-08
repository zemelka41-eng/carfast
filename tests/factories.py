import factory
from django.utils.text import slugify

from catalog.models import Category, Lead, ModelVariant, Product, ProductImage, Series, SeriesCategorySEO


class SeriesFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Series

    name = factory.Sequence(lambda n: f"Series {n}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    description_ru = ""
    description_en = ""


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Category {n}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))


class ModelVariantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ModelVariant

    brand = factory.SubFactory(SeriesFactory)
    line = factory.Sequence(lambda n: f"XTEST{n}")
    wheel_formula = "1x1"
    name = factory.LazyAttribute(lambda obj: f"{obj.line} {obj.wheel_formula}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    sort_order = 0


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    sku = factory.Sequence(lambda n: f"SKU-{n}")
    slug = factory.LazyAttribute(lambda obj: slugify(obj.sku))
    series = factory.SubFactory(SeriesFactory)
    category = factory.SubFactory(CategoryFactory)
    model_name_ru = factory.Faker("word")
    model_name_en = factory.Faker("word")
    short_description_ru = ""
    short_description_en = ""
    availability = Product.Availability.IN_STOCK
    published = True


class ProductImageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductImage

    product = factory.SubFactory(ProductFactory)
    image = factory.django.ImageField(color="blue", filename="product.jpg")
    order = factory.Sequence(int)
    alt_ru = factory.LazyAttribute(lambda obj: obj.product.model_name_ru)
    alt_en = factory.LazyAttribute(lambda obj: obj.product.model_name_en)


class LeadFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Lead

    product = factory.SubFactory(ProductFactory)
    name = factory.Faker("name")
    phone = factory.Faker("phone_number")
    email = factory.Faker("email")
    message = factory.Faker("sentence")


class SeriesCategorySEOFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SeriesCategorySEO

    series = factory.SubFactory(SeriesFactory)
    category = factory.SubFactory(CategoryFactory)
    seo_description = ""
    seo_faq = ""
