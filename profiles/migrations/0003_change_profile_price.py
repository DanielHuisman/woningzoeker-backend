# Generated by Django 3.2.6 on 2021-08-29 15:27

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0002_fix_fields'),
    ]

    operations = [
        migrations.RenameField(
            model_name='profile',
            old_name='max_price',
            new_name='max_price_base',
        ),
        migrations.RenameField(
            model_name='profile',
            old_name='min_price',
            new_name='min_price_base',
        ),
    ]