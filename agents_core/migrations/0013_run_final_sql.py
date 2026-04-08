from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agents_core', '0012_run_feedback'),
    ]

    operations = [
        migrations.AddField(
            model_name='run',
            name='final_sql',
            field=models.TextField(blank=True, default=''),
        ),
    ]
