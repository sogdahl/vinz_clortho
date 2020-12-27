__author__ = 'Steven Ogdahl'

from datetime import datetime, timedelta
import pymongo
#from django.db import models

def dict_iterator(cursor, col_names):
    for row in cursor.fetchall():
        yield dict(zip(col_names, row))

class Credential(object):
    def __init__(self, key, username=None, password=None, max_checkouts=0, throttle_seconds=0, **kwargs):
        self.id = kwargs.get('_id', None)
        self.key = key
        self.username = username
        self.password = password
        self.max_checkouts = max_checkouts
        self.throttle_seconds = throttle_seconds

        self.db = kwargs.get('db', None)

    @property
    def throttle_timespan(self):
        return timedelta(seconds=self.throttle_seconds)

    @property
    def pending(self):
        if not self.db:
            return None
        return self.db.cm_request.count(
            filter={
                'key': self.key,
                'status': {
                    '$in': [
                        CMRequest.SUBMITTED,
                        CMRequest.QUEUING,
                        CMRequest.CANCEL,
                        CMRequest.GIVEN_OUT
                    ]
                }
            }
        )

    def _retrieve_statistics(self):
        from django.db import connection
        cursor = connection.cursor()
        cursor.execute(u'''
            SELECT
            AVG(checkout_timestamp - submission_timestamp) AS avg_wait,
            AVG(checkin_timestamp - checkout_timestamp) AS avg_usage,
            STDDEV(extract(epoch from checkout_timestamp - submission_timestamp)) * INTERVAL '1 second' AS stddev_wait,
            STDDEV(extract(epoch from checkin_timestamp - checkout_timestamp)) * INTERVAL '1 second' AS stddev_usage
            FROM "scrapeService_cmrequest"
            WHERE credential_id = {0} AND status = {1}
            '''.format(self.id, CMRequest.COMPLETED))
        items = list(dict_iterator(cursor, ['avg_wait', 'avg_usage', 'stddev_wait', 'stddev_usage']))
        self._average_wait_time = (items[0]['avg_wait'] or timedelta()).total_seconds()
        self._average_usage_time = (items[0]['avg_usage'] or timedelta()).total_seconds()
        self._stddev_wait_time = (items[0]['stddev_wait'] or timedelta()).total_seconds()
        self._stddev_usage_time = (items[0]['stddev_usage'] or timedelta()).total_seconds()

    @property
    def in_use(self):
        if not self.db:
            return None
        return self.db.cm_request.count(
            filter={
                'credential': self.id,
                'status': {
                    '$in': [
                        CMRequest.CANCEL,
                        CMRequest.GIVEN_OUT,
                        CMRequest.IN_USE,
                        CMRequest.RETURNED
                    ]
                }
            }
        )

    @property
    def average_wait_time(self):
        if self._average_wait_time == -1:
            self._retrieve_statistics()
        return self._average_wait_time

    @property
    def average_usage_time(self):
        if self._average_usage_time == -1:
            self._retrieve_statistics()
        return self._average_usage_time

    @property
    def stddev_wait_time(self):
        if self._stddev_wait_time == -1:
            self._retrieve_statistics()
        return self._stddev_wait_time

    @property
    def stddev_usage_time(self):
        if self._stddev_usage_time == -1:
            self._retrieve_statistics()
        return self._stddev_usage_time

    @property
    def last_checkout_timestamp(self):
        if not self.db:
            return None
        request = self.db.cm_request.find_one(
            filter={ 'credential': self.id },
            sort=[('submission_timestamp', pymongo.DESCENDING)]
        )
        if request:
            return request['submission_timestamp']
        return None

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'username': self.username,
            'password': self.password,
            'max_checkouts': self.max_checkouts,
            'throttle_seconds': self.throttle_seconds,
            'pending': self.pending,
            'in_use': self.in_use
        }


    def update(self, **kwargs):
        if 'db' in kwargs:
            self.db = kwargs.pop('db')
        self.db.credential.update_one(
            filter={'_id': self.id},
            update={'$set': kwargs}
        )

    @staticmethod
    def find(db, **kwargs):
        return [Credential(db=db, **c) for c in db.credential.find(**kwargs)]

    @staticmethod
    def find_one(db, **kwargs):
        c = db.credential.find_one(**kwargs)
        if c:
            c = Credential(db=db, **c)
        return c


class CMRequest(object):
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

    def __init__(self, credential=None, client='', key='', priority=0, status=UNKNOWN, submission_timestamp=None,
                 checkout_timestamp=None, checkin_timestamp=None, **kwargs):
        self.id = kwargs.get('_id', None)
        self.credential = credential
        self.client = client
        self.key = key
        self.priority = priority
        self.status = status
        self.submission_timestamp = submission_timestamp or datetime.now()
        self.checkout_timestamp = checkout_timestamp
        self.checkin_timestamp = checkin_timestamp

        self.db = kwargs.get('db', None)


    def to_dict(self):
        return {
            'id': self.id,
            'credential': self.credential,
            'client': self.client,
            'key': self.key,
            'priority': self.priority,
            'status': self.status,
            'submission_timestamp': self.submission_timestamp,
            'checkout_timestamp': self.checkout_timestamp,
            'checkin_timestamp': self.checkin_timestamp
        }

    def update(self, **kwargs):
        if 'db' in kwargs:
            self.db = kwargs.pop('db')
        self.db.cm_request.update_one(
            filter={'_id': self.id},
            update={'$set': kwargs}
        )

    @staticmethod
    def find(db, **kwargs):
        return [CMRequest(db=db, **cmr) for cmr in db.cm_request.find(**kwargs)]


    @staticmethod
    def find_one(db, **kwargs):
        cmr = db.cm_request.find_one(**kwargs)
        if cmr:
            cmr = CMRequest(db=db, **cmr)
        return cmr