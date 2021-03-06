from uuid import uuid4

from django.db import models
from django.contrib.auth.models import User

from woningzoeker.fields import EncryptedTextField


class Platform(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)

    name = models.CharField(max_length=255, unique=True)
    handle = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name


class Corporation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)

    name = models.CharField(max_length=255, unique=True)
    handle = models.CharField(max_length=255, unique=True)

    platforms = models.ManyToManyField(Platform, related_name='corporations')
    cities = models.ManyToManyField('residences.City', related_name='corporations')

    def __str__(self):
        return self.name


class Registration(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)

    identifier = models.CharField(max_length=255)
    credentials = EncryptedTextField()
    # TODO: add search criteria

    platform = models.ForeignKey(Platform, related_name='registrations', on_delete=models.CASCADE)
    user = models.ForeignKey(User, related_name='registrations', on_delete=models.CASCADE)

    def __str__(self):
        return f'{self.platform.name} - {self.identifier}'
