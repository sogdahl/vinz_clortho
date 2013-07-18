__author__ = 'Steven Ogdahl'
__version__ = '0.1'

import sys
import time
import socket
from datetime import datetime, timedelta

from daemon import Daemon

ENV_HOST = socket.gethostname()

#sys.path.append(r'C:\Users\Steven Ogdahl\Documents\PyCharmProjects\vanguard\vdsPortal')

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

elif ENV_HOST == 'newstage.vanguardds.com':
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
        TIME_ZONE = 'US/Pacific'
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
        TIME_ZONE = 'US/Pacific'
    )

#print sys.path
from scrapeService.copied_models import Credential, CMRequest

# Seconds to use as a timeout
WAITING_TIMEOUT = 90
USING_TIMEOUT = 600
POLL_INTERVAL = 2

class VCDaemon(Daemon):
    LEVEL_ERROR = 0
    LEVEL_WARNING = 1
    LEVEL_INFO = 2

    min_log_level = LEVEL_WARNING

    def __init__(self, *args, **kwargs):
        Daemon.__init__(self, *args, **kwargs)
        self.min_log_level = kwargs.get('min_log_level', VCDaemon.LEVEL_WARNING)

    def log(self, level, request, message):
        if level > self.min_log_level:
            return
        if request:
            print "[{0}] RequestId: {1} -- {2}".format(datetime.now().strftime('%H:%M:%S.%f'), request.id, message)
        else:
            print "[{0}] {1}".format(datetime.now().strftime('%H:%M:%S.%f'), message)

    def run(self):
        self.log(VCDaemon.LEVEL_INFO, None, "Running with a polling interval of {0} seconds".format(POLL_INTERVAL))
        self.log(VCDaemon.LEVEL_INFO, None, "Credential waiting timeout is {0} seconds".format(WAITING_TIMEOUT))
        self.log(VCDaemon.LEVEL_INFO, None, "Credential using timeout is {0} seconds".format(USING_TIMEOUT))
        while True:
            new_requests = CMRequest.objects.filter(status=CMRequest.SUBMITTED)
            for new_request in new_requests:
                credentials = Credential.objects.filter(key=new_request.key)

                # If we didn't find any credentials, then error out this request
                if len(credentials) == 0:
                    self.log(VCDaemon.LEVEL_ERROR, new_request, "No such key found: {0}".format(new_request.key))
                    new_request.status = CMRequest.NO_SUCH_KEY
                    new_request.save()
                    continue

                self.log(VCDaemon.LEVEL_INFO, new_request, "Putting into queue")
                new_request.status = CMRequest.QUEUING
                new_request.save()

            # This is mainly a formality, but just mark all the ones that are a
            # status of CANCEL to CANCELED instead.  This indicates that the
            # server acknowledged the order to cancel
            cancel_requests = CMRequest.objects.\
                filter(status=CMRequest.CANCEL)
            for cancel_request in cancel_requests:
                self.log(VCDaemon.LEVEL_INFO, cancel_request, "Canceled by client")
                cancel_request.status = CMRequest.CANCELED
                cancel_request.save()

            returned_credentials = CMRequest.objects.\
                filter(status=CMRequest.RETURNED)
            for returned_credential in returned_credentials:
                self.log(VCDaemon.LEVEL_INFO, returned_credential, "Credentials returned by client")
                returned_credential.status = CMRequest.COMPLETED
                returned_credential.checkin_timestamp = datetime.now()
                returned_credential.save()

            pending_credentials = CMRequest.objects.\
                filter(status=CMRequest.GIVEN_OUT)
            for pending_credential in pending_credentials:
                if (datetime.now() - pending_credential.checkout_timestamp).total_seconds() > WAITING_TIMEOUT:
                    self.log(VCDaemon.LEVEL_WARNING, pending_credential, "Timed out waiting for client to receive credentials")
                    pending_credential.status = CMRequest.TIMED_OUT_WAITING
                    pending_credential.save()

            in_use_credentials = CMRequest.objects.\
                filter(status=CMRequest.IN_USE)
            for in_use_credential in in_use_credentials:
                if (datetime.now() - in_use_credential.checkout_timestamp).total_seconds() > USING_TIMEOUT:
                    self.log(VCDaemon.LEVEL_WARNING, in_use_credential, "Timed out waiting for client to return credentials")
                    in_use_credential.status = CMRequest.TIMED_OUT_USING
                    in_use_credential.save()

            # This is the meat of the big loop.  This section is the one that
            # will be doling out the credentials on a first-come, first-serve
            # basis, with priority overriding that.
            queued_requests = CMRequest.objects.\
                filter(status=CMRequest.QUEUING).\
                order_by('-priority', 'submission_timestamp', 'id')
            for queued_request in queued_requests:
                available_credentials = Credential.objects.filter(key=queued_request.key)
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
                        self.log(VCDaemon.LEVEL_INFO, queued_request, "Assigning CredentialId: {0} to client".format(available_credential.id))
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
                if arg[-1] in ('e', 'E'):
                    kwdict['min_log_level'] = VCDaemon.LEVEL_ERROR
                elif arg[-1] in ('w', 'W'):
                    kwdict['min_log_level'] = VCDaemon.LEVEL_WARNING
                elif arg[-1] in ('i', 'I'):
                    kwdict['min_log_level'] = VCDaemon.LEVEL_INFO
                else:
                    print "unknown parameter '{0}' specified for -l.  Please use E, W, or I"
                    sys.exit(2)
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
        elif 'run' == sys.argv[-1]:
            daemon.run()
        else:
            print "Unknown command"
            sys.exit(2)
        sys.exit(0)
    else:
        print "usage: %s [OPTIONS] start|stop|restart|run" % sys.argv[0]
        print "OPTIONS can be any of (default in parenthesis):"
        print "\t-l(E|W|I)\tSets the minimum logging level to Errors, Warnings, or Infos (W)"
        print "\t-p##\tSets main polling interval (2)"
        print "\t-w##\tSets credential waiting timeout value (90)"
        print "\t-u##\tSets credential using timeout value (600)"
        sys.exit(2)
