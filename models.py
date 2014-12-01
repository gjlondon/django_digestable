from django.db import models
from django.conf import settings
from django.contrib.auth import get_user_model


class EmailTime(models.Model):
    """
    Store information when to send next email to a user.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL)
    time = models.DateTimeField()


class SentItems(models.Model):

    user = models.ForeignKey(settings.AUTH_USER_MODEL)
    date = models.DateTimeField(auto_now=True)
    # when sending a concert once again update the date field
    type = models.TextField()
    item_id = models.TextField()

    class Meta:
        unique_together = ('user', 'item_id',)
        abstract = True
