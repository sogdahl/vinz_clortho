#!/usr/bin/python
__author__ = 'Steven Ogdahl'
__version__ = '0.3a'

import sys
import time
import socket
import logging
from datetime import datetime, timedelta

from daemon import Daemon

ENV_HOST = socket.gethostname()

from django.conf import settings

if ENV_HOST == 'Lynx':
    settings.configure(
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql_psycopg2',
                'NAME': 'workportal',
                'USER': 'workportal',
                'PASSWORD': 'PYddT2rEk02d',
                'HOST': '127.0.0.1',
                'PORT': '5432',
                'OPTIONS': {'autocommit': True,}
            }
        },
        TIME_ZONE = 'US/Central'
    )

elif ENV_HOST == 'stage.vanguardds.com':
    settings.configure(
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql_psycopg2',
                'NAME': 'workportal',
                'USER': 'workportal',
                'PASSWORD': 'PYddT2rEk02d',
                'HOST': '127.0.0.1',
                'PORT': '5432',
                'OPTIONS': {'autocommit': True,}
            }
        },
        TIME_ZONE = 'UTC'
    )

elif ENV_HOST == 'work.vanguardds.com':
    settings.configure(
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql_psycopg2',
                'NAME': 'workportal',
                'USER': 'workportal',
                'PASSWORD': 'PYddT2rEk02d',
                'HOST': '127.0.0.1',
                'PORT': '5432',
                'OPTIONS': {'autocommit': True,}
            }
        },
        TIME_ZONE = 'UTC'
    )

from scrapeService.copied_models import Credential, CMRequest

# Seconds to use as a timeout
WAITING_TIMEOUT = 90
USING_TIMEOUT = 600
POLL_INTERVAL = 2

class VCDaemon(Daemon):
    timestamp_format = '%Y-%m-%d %H:%M:%S'
    min_log_level = logging.WARNING
    logfile = 'vinz_clortho.log'

    def __init__(self, *args, **kwargs):
        Daemon.__init__(self, *args, **kwargs)
        self.min_log_level = kwargs.get('min_log_level', logging.WARNING)
        self.logfile = kwargs.get('logfile', 'vinz_clortho.log')
        logging.basicConfig(
            filename=self.logfile,
            level=self.min_log_level,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            datefmt=self.timestamp_format
        )

    def log(self, level, message, request=None):
        if request:
            logstr = "RequestId: {0} -- {1}".format(request.id, message)
        else:
            logstr = message
        logging.log(level, logstr)

    def run(self):
        self.log(logging.INFO, "Running with a polling interval of {0} seconds".format(POLL_INTERVAL))
        self.log(logging.INFO, "Credential waiting timeout is {0} seconds".format(WAITING_TIMEOUT))
        self.log(logging.INFO, "Credential using timeout is {0} seconds".format(USING_TIMEOUT))
        while True:
            new_requests = CMRequest.objects.filter(status=CMRequest.SUBMITTED)
            if new_requests.count() > 0:
                self.log(logging.DEBUG, "Processing {0} new requests".format(new_requests.count()))
            for new_request in new_requests:
                credentials = Credential.objects.filter(key=new_request.key)

                # If we didn't find any credentials, then error out this request
                if len(credentials) == 0:
                    self.log(logging.ERROR, "No such key found: {0}".format(new_request.key), new_request)
                    new_request.status = CMRequest.NO_SUCH_KEY
                    new_request.save()
                    continue

                self.log(logging.INFO, "Putting into queue", new_request)
                new_request.status = CMRequest.QUEUING
                new_request.save()

            # This is mainly a formality, but just mark all the ones that are a
            # status of CANCEL to CANCELED instead.  This indicates that the
            # server acknowledged the order to cancel
            cancel_requests = CMRequest.objects.\
                filter(status=CMRequest.CANCEL)
            if cancel_requests.count() > 0:
                self.log(logging.DEBUG, "Processing {0} cancel requests".format(cancel_requests.count()))
            for cancel_request in cancel_requests:
                self.log(logging.INFO, "Canceled by client", cancel_request)
                cancel_request.status = CMRequest.CANCELED
                cancel_request.save()

            returned_credentials = CMRequest.objects.\
                filter(status=CMRequest.RETURNED)
            if returned_credentials.count() > 0:
                self.log(logging.DEBUG, "Processing {0} returned credentials".format(returned_credentials.count()))
            for returned_credential in returned_credentials:
                self.log(logging.INFO, "CredentialId {0} returned by client".format(returned_credential.credential.id), returned_credential)
                returned_credential.status = CMRequest.COMPLETED
                returned_credential.checkin_timestamp = datetime.now()
                returned_credential.save()

            pending_credentials = CMRequest.objects.\
                filter(status=CMRequest.GIVEN_OUT)
            if pending_credentials.count() > 0:
                self.log(logging.DEBUG, "Testing {0} given out credentials for time-out".format(pending_credentials.count()))
            for pending_credential in pending_credentials:
                if (datetime.now() - pending_credential.checkout_timestamp).total_seconds() > WAITING_TIMEOUT:
                    self.log(logging.WARNING, "Timed out waiting for client to receive credentials", pending_credential)
                    pending_credential.status = CMRequest.TIMED_OUT_WAITING
                    pending_credential.save()

            in_use_credentials = CMRequest.objects.\
                filter(status=CMRequest.IN_USE)
            if in_use_credentials.count() > 0:
                self.log(logging.DEBUG, "Testing {0} in-use credentials for time-out".format(in_use_credentials.count()))
            for in_use_credential in in_use_credentials:
                if (datetime.now() - in_use_credential.checkout_timestamp).total_seconds() > USING_TIMEOUT:
                    self.log(logging.WARNING, "Timed out waiting for client to return credentials", in_use_credential)
                    in_use_credential.status = CMRequest.TIMED_OUT_USING
                    in_use_credential.save()

            # This is the meat of the big loop.  This section is the one that
            # will be doling out the credentials on a first-come, first-serve
            # basis, with priority overriding that.
            queued_requests = CMRequest.objects.\
                filter(status=CMRequest.QUEUING).\
                order_by('-priority', 'submission_timestamp', 'id')
            if queued_requests.count() > 0:
                self.log(logging.DEBUG, "Checking credentials to give out for {0} queued requests".format(queued_requests.count()))
            for queued_request in queued_requests:
                available_credentials = Credential.objects.filter(key=queued_request.key)
                if available_credentials.count() > 0:
                    self.log(logging.DEBUG, "Testing {0} available credentials for queued request {1}".format(available_credentials.count(), queued_request.id))
                for available_credential in available_credentials:
                    # Only give out credentials if there are any available to give out
                    in_use_credentials = CMRequest.objects.\
                        filter(credential=available_credential, status__in=[
                            CMRequest.GIVEN_OUT,
                            CMRequest.IN_USE,
                            CMRequest.RETURNED
                        ]).count()

                    # Also, throttle how frequently we are allowed to give out this credential
                    credential_frequency = CMRequest.objects.\
                        filter(credential=available_credential, status__in=[
                            CMRequest.GIVEN_OUT,
                            CMRequest.TIMED_OUT_WAITING,
                            CMRequest.IN_USE,
                            CMRequest.TIMED_OUT_USING,
                            CMRequest.RETURNED,
                            CMRequest.COMPLETED
                        ], checkout_timestamp__gte=datetime.now() - timedelta(seconds=available_credential.throttle_timespan)).count()

                    if (available_credential.max_checkouts == 0 or in_use_credentials < available_credential.max_checkouts) and \
                            (available_credential.throttle_timespan == 0 or credential_frequency == 0):
                        # We found a credential available to be used! Yay!
                        self.log(logging.INFO, "Assigning CredentialId: {0} to client".format(available_credential.id), queued_request)
                        queued_request.credential = available_credential
                        queued_request.status = CMRequest.GIVEN_OUT
                        queued_request.checkout_timestamp = datetime.now()
                        queued_request.save()
                        break

            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    kwdict = {}
    #  VERY basic options parsing
    if len(sys.argv) >= 2:
        for arg in sys.argv:
            if arg[:2] == '-l':
                if arg[-1] in ('f', 'F'):
                    kwdict['min_log_level'] = logging.FATAL
                elif arg[-1] in ('c', 'C'):
                    kwdict['min_log_level'] = logging.CRITICAL
                elif arg[-1] in ('e', 'E'):
                    kwdict['min_log_level'] = logging.ERROR
                elif arg[-1] in ('w', 'W'):
                    kwdict['min_log_level'] = logging.WARNING
                elif arg[-1] in ('i', 'I'):
                    kwdict['min_log_level'] = logging.INFO
                elif arg[-1] in ('d', 'D'):
                    kwdict['min_log_level'] = logging.DEBUG
                else:
                    print "unknown parameter '{0}' specified for -l.  Please use F, C, E, W, I, or D"
                    sys.exit(2)
            if arg[:2] == '-L':
                kwdict['logfile'] = arg[2:]
            elif arg[:2] == '-p':
                POLL_INTERVAL = int(arg[2:])
            elif arg[:2] == '-w':
                WAITING_TIMEOUT = int(arg[2:])
            elif arg[:2] == '-u':
                USING_TIMEOUT = int(arg[2:])
            elif arg[:2] == '-v':
                print "%s version %s" % (sys.argv[0], __version__)
                print "Many Shuvs and Zuuls knew what it was to be roasted"
                print "in the depths of the Slor that day, I can tell you!"
                sys.exit(2)

    daemon = VCDaemon('/tmp/daemon-credential_manager.pid', **kwdict)
    if len(sys.argv) >= 2:
        if 'start' == sys.argv[-1]:
            daemon.start()
        elif 'stop' == sys.argv[-1]:
            daemon.stop()
        elif 'restart' == sys.argv[-1]:
            daemon.restart()
        elif 'status' == sys.argv[-1]:
            daemon.status()
        elif 'run' == sys.argv[-1]:
            daemon.run()
        else:
            print "Unknown command"
            sys.exit(2)
        sys.exit(0)
    else:
        print "usage: %s [OPTIONS] start|stop|restart|run" % sys.argv[0]
        print "OPTIONS can be any of (default in parenthesis):"
        print "  -l(F|C|E|W|I|D)\tSets the minimum logging level to Fatal, Critical, "
        print "\t\tError, Warning, or Info, or Debug (W)"
        print "  -LFILE\tSets logfile to FILE"
        print "\t\tLeave blank for STDOUT"
        print "  -p##\t\tSets main polling interval (2)"
        print "  -w##\t\tSets credential waiting timeout value (90)"
        print "  -u##\t\tSets credential using timeout value (600)"
        print "  -v\t\tPrints the current version and exits"
        sys.exit(2)
