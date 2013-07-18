__author__ = 'Steven Ogdahl'

# Since the 'vanguard' project is such a cluster-f*ck of modules importing
# each other and circular references, it's absolutely impossible to use the
# applications by just importing their .models module.  So, in order to get it
# to work properly, I have just copied the important models into this file.
# This is not my preferred method of doing this; I'd much rather keep a single
# source, especially considering that these are DB models, but what can you do.

from datetime import datetime
from django.db import models


class Credential(models.Model):
    key = models.CharField(max_length=200, verbose_name="Key", null=False)
    username = models.CharField(max_length=100, verbose_name="Username", null=True)
    password = models.CharField(max_length=100, verbose_name="Password", null=True)
    max_checkouts = models.PositiveIntegerField(verbose_name="Maximum Checkouts", default=0, null=True)
    throttle_timespan = models.PositiveIntegerField(verbose_name="Throttle Timespan in seconds", default=0, null=True)

    @property
    def pending(self):
        return CMRequest.objects.filter(key=self.key, status__in=[
            CMRequest.SUBMITTED,
            CMRequest.QUEUING,
            CMRequest.CANCEL,
            CMRequest.GIVEN_OUT
        ]).count()


class CMRequest(models.Model):
    UNKNOWN = 0
    SUBMITTED = 1
    QUEUING = 2
    CANCEL = 3
    CANCELED = 4
    GIVEN_OUT = 5
    IN_USE = 6
    RETURNED = 7
    COMPLETED = 8
    TIMED_OUT_WAITING = 9
    TIMED_OUT_USING = 10
    FAILED = 11
    NO_SUCH_KEY = 12

    STATUS_CHOICES = (
        (UNKNOWN, 'Unknown'),
        (SUBMITTED, 'Request submitted'),
        (QUEUING, 'Queuing for credentials'),
        (CANCEL, 'Client indicated that request should be canceled'),
        (CANCELED, 'Request canceled by client'),
        (GIVEN_OUT, 'Credentials have been given out (but not retrieved)'),
        (IN_USE, 'Credentials are in use'),
        (RETURNED, 'Credentials have been returned'),
        (COMPLETED, 'Request completed'),
        (TIMED_OUT_WAITING, 'Timed out waiting for client to take credentials'),
        (TIMED_OUT_USING, 'Timed out returning credentials'),
        (FAILED, 'Request failed'),
        (NO_SUCH_KEY, 'No such key found')
    )

    credential = models.ForeignKey(Credential, default=None, null=True, related_name="+")
    client = models.CharField(max_length=1000, verbose_name="Client identifier", null=False, default='')
    key = models.CharField(max_length=200, verbose_name="Key", null=False, default='')
    priority = models.PositiveIntegerField(default=0)
    status = models.PositiveIntegerField(choices=STATUS_CHOICES, default=UNKNOWN)
    submission_timestamp = models.DateTimeField(null=False, default=datetime.now())
    checkout_timestamp = models.DateTimeField(null=True)
    checkin_timestamp = models.DateTimeField(null=True)