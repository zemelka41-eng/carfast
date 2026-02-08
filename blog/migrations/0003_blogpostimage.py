from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("blog", "0002_seed_initial_post"),
    ]

    operations = [
        migrations.CreateModel(
            name="BlogPostImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="blog/gallery/")),
                ("alt", models.CharField(blank=True, max_length=200)),
                ("caption", models.CharField(blank=True, max_length=200)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("post", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="images", to="blog.blogpost")),
            ],
            options={
                "verbose_name": "Изображение статьи",
                "verbose_name_plural": "Изображения статьи",
                "ordering": ["sort_order", "id"],
            },
        ),
    ]
