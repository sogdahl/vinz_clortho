#!/usr/bin/python
__author__ = 'Steven Ogdahl'
__version__ = '0.20'

import sys
import time
import logging
import signal
from datetime import datetime

from daemon import Daemon
from models import Credential, CMRequest
import mongo

# Seconds to use as a timeout
WAITING_TIMEOUT = 90
USING_TIMEOUT = 600
POLL_INTERVAL = 2

class VCDaemon(Daemon):
    timestamp_format = '%Y-%m-%d %H:%M:%S'
    min_log_level = logging.WARNING
    logfile = 'vinz_clortho.log'
    IS_RUNNING = False
    SHOULD_BE_RUNNING = False
    PROCESS_STEP = None
    PROCESS_COUNT = 0
    PROCESS_INDEX = 0

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
            logstr = "RequestId: {0} ({2}) -- {1}".format(request.id, message, request.key)
        else:
            logstr = message
        logging.log(level, logstr)

    def graceful_term(self, signum, frame):
        self.log(logging.INFO, "Caught SigTerm... terminating gracefully.")
        self.SHOULD_BE_RUNNING = False
        if self.PROCESS_STEP:
            self.log(logging.INFO, "Currently processing {0}: {1}/{2}".format(
                self.PROCESS_STEP, self.PROCESS_INDEX, self.PROCESS_COUNT)
            )
        previous_step = self.PROCESS_STEP
        GRACE_WAIT = 0.2
        while self.IS_RUNNING:
            if self.PROCESS_STEP != previous_step:
                self.log(logging.INFO, "Currently processing {0}: {1}/{2}".format(
                    self.PROCESS_STEP, self.PROCESS_INDEX, self.PROCESS_COUNT)
                )
            previous_step = self.PROCESS_STEP
            self.log(logging.DEBUG, "Going to sleep for {0} seconds".format(GRACE_WAIT))
            time.sleep(GRACE_WAIT)
        self.log(logging.INFO, "Gracefully terminated.")
        sys.exit(0)

    def run(self):
        self.log(logging.INFO, "Running with a polling interval of {0} seconds".format(POLL_INTERVAL))
        self.log(logging.INFO, "Credential waiting timeout is {0} seconds".format(WAITING_TIMEOUT))
        self.log(logging.INFO, "Credential using timeout is {0} seconds".format(USING_TIMEOUT))

        connection = mongo.connect_db()
        db = connection.vinz_clortho

        signal.signal(signal.SIGTERM, self.graceful_term)
        self.SHOULD_BE_RUNNING = True

        while self.SHOULD_BE_RUNNING:
            self.IS_RUNNING = True

            new_requests = CMRequest.find(db, filter={'status': CMRequest.SUBMITTED})
            self.PROCESS_STEP = "New Requests"
            self.PROCESS_COUNT = len(new_requests)
            self.PROCESS_INDEX = 0
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Processing {0} new requests".format(self.PROCESS_COUNT))
                self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in new_requests])))
            for new_request in new_requests:
                self.PROCESS_INDEX += 1
                credentials = Credential.find(db, filter={'key': new_request.key})

                # If we didn't find any credentials, then error out this request
                if len(credentials) == 0:
                    self.log(logging.ERROR, "No such key found: {0}".format(new_request.key), new_request)
                    new_request.update(status=CMRequest.NO_SUCH_KEY)
                    continue

                self.log(logging.INFO, "Putting into queue", new_request)
                new_request.update(status=CMRequest.QUEUING)
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Done processing new requests")


            # This is mainly a formality, but just mark all the ones that are a
            # status of CANCEL to CANCELED instead.  This indicates that the
            # server acknowledged the order to cancel
            cancel_requests = CMRequest.find(db, filter={'status': CMRequest.CANCEL})
            self.PROCESS_STEP = "Cancel Requests"
            self.PROCESS_COUNT = len(cancel_requests)
            self.PROCESS_INDEX = 0
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Processing {0} cancel requests".format(self.PROCESS_COUNT))
                self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in cancel_requests])))
            for cancel_request in cancel_requests:
                self.PROCESS_INDEX += 1
                self.log(logging.INFO, "Canceled by client", cancel_request)
                cancel_request.update(status=CMRequest.CANCELED)
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Done processing cancel requests")

            returned_credentials = CMRequest.find(db, filter={'status': CMRequest.RETURNED})
            self.PROCESS_STEP = "Returned Credentials"
            self.PROCESS_COUNT = len(returned_credentials)
            self.PROCESS_INDEX = 0
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Processing {0} returned credentials".format(self.PROCESS_COUNT))
                self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in returned_credentials])))
            for returned_credential in returned_credentials:
                self.PROCESS_INDEX += 1
                credential = Credential.find_one(db, filter={'_id': returned_credential.credential})
                returned_credential.status = CMRequest.COMPLETED
                returned_credential.checkin_timestamp = datetime.now()
                self.log(logging.INFO, "CredentialId {0} returned by client (Elapsed: {1:.1f}s)".format(
                    credential.id,
                    (returned_credential.checkin_timestamp - returned_credential.checkout_timestamp).total_seconds()
                ), returned_credential)
                returned_credential.update(status=CMRequest.COMPLETED, checkin_timestamp=datetime.now())
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Done processing returned credentials")

            pending_credentials = CMRequest.find(db, filter={'status': CMRequest.GIVEN_OUT})
            self.PROCESS_STEP = "Pending Credentials"
            self.PROCESS_COUNT = len(pending_credentials)
            self.PROCESS_INDEX = 0
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Testing {0} given out credentials for time-out".format(self.PROCESS_COUNT))
                self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in pending_credentials])))
            for pending_credential in pending_credentials:
                self.PROCESS_INDEX += 1
                if (datetime.now() - pending_credential.checkout_timestamp).total_seconds() > WAITING_TIMEOUT:
                    self.log(logging.WARNING, "Timed out waiting for client to receive credentials", pending_credential)
                    pending_credential.update(status=CMRequest.TIMED_OUT_WAITING)
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Done testing given-out credentials for time-out")

            in_use_credentials = CMRequest.find(db, filter={
                'status': {'$in': (CMRequest.IN_USE, CMRequest.CANCEL)},
                'checkout_timestamp': {'$exists': True}
            })
            self.PROCESS_STEP = "In-use Credentials"
            self.PROCESS_COUNT = len(in_use_credentials)
            self.PROCESS_INDEX = 0
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Testing {0} in-use credentials for time-out".format(self.PROCESS_COUNT))
                self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in in_use_credentials])))
            for in_use_credential in in_use_credentials:
                self.PROCESS_INDEX += 1
                if (datetime.now() - in_use_credential.checkout_timestamp).total_seconds() > USING_TIMEOUT:
                    self.log(logging.WARNING, "Timed out waiting for client to return credentials", in_use_credential)
                    in_use_credential.update(status=CMRequest.TIMED_OUT_USING)
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Done testing in-use credentials for time-out")

            # This is the meat of the big loop.  This section is the one that
            # will be doling out the credentials on a first-come, first-serve
            # basis, with priority overriding that.
            queued_requests = CMRequest.find(db, filter={'status': CMRequest.QUEUING}, sort=
                [('priority', mongo.DESCENDING), ('submission_timestamp', mongo.ASCENDING), ('_id', mongo.ASCENDING)]
            )
            self.PROCESS_STEP = "Queued Requests"
            self.PROCESS_COUNT = len(queued_requests)
            self.PROCESS_INDEX = 0
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Checking credentials to give out for {0} queued requests".format(
                    self.PROCESS_COUNT)
                )
                self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in queued_requests])))
            for queued_request in queued_requests:
                self.PROCESS_INDEX += 1
                available_credentials = Credential.find(db, filter={'key': queued_request.key})
                if len(available_credentials) > 0:
                    self.log(logging.DEBUG, "Testing {0} available credentials for queued request".format(
                        len(available_credentials)
                    ), queued_request)
                    self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(c.id) for c in available_credentials])))
                for available_credential in available_credentials:
                    # Only give out credentials if there are any available to give out
                    in_use_credentials = available_credential.in_use

                    # Also, throttle how frequently we are allowed to give out this credential
                    credential_frequency = len(CMRequest.find(db, filter={
                        'credential': available_credential.id,
                        'status': {
                            '$in': (
                                CMRequest.GIVEN_OUT,
                                CMRequest.TIMED_OUT_WAITING,
                                CMRequest.IN_USE,
                                CMRequest.TIMED_OUT_USING,
                                CMRequest.RETURNED,
                                CMRequest.COMPLETED
                            )
                        },
                        'checkout_timestamp': {
                            '$gte': datetime.now() - available_credential.throttle_timespan
                        }
                    }))

                    if (available_credential.max_checkouts == 0 or
                            in_use_credentials < available_credential.max_checkouts) and \
                            (available_credential.throttle_seconds == 0 or credential_frequency == 0):
                        # We found a credential available to be used! Yay!
                        queued_request.credential = available_credential.id
                        queued_request.status = CMRequest.GIVEN_OUT
                        queued_request.checkout_timestamp = datetime.now()
                        self.log(logging.INFO, "Assigning CredentialId: {0} to client (waited {1:.1f}s)".format(
                            available_credential.id,
                            (queued_request.checkout_timestamp - queued_request.submission_timestamp).total_seconds()
                        ), queued_request)
                        queued_request.update(
                            credential=available_credential.id,
                            status=CMRequest.GIVEN_OUT,
                            checkout_timestamp=datetime.now()
                        )
                        break
            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Done checking credentials to give out for queued requests")

            self.IS_RUNNING = False
            self.log(logging.DEBUG, "Going to sleep for {0} seconds".format(POLL_INTERVAL))
            time.sleep(POLL_INTERVAL)

def print_help():
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

if __name__ == "__main__":
    kwdict = {}
    #  VERY basic options parsing
    if len(sys.argv) >= 2:
        for arg in sys.argv[1:]:
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
                    print "unknown parameter '{0}' specified for -l.  Please use F, C, E, W, I, or D".format(arg[-1])
                    sys.exit(2)
            elif arg[:2] == '-L':
                kwdict['logfile'] = arg[2:]
            elif arg[:2] == '-p':
                POLL_INTERVAL = int(arg[2:])
            elif arg[:2] == '-w':
                WAITING_TIMEOUT = int(arg[2:])
            elif arg[:2] == '-u':
                USING_TIMEOUT = int(arg[2:])
            elif arg in ('-h', '--help'):
                print_help()
                sys.exit(1)
            elif arg in ('-v', '--version'):
                print "%s version %s" % (sys.argv[0], __version__)
                print "Many Shuvs and Zuuls knew what it was to be roasted"
                print "in the depths of the Slor that day, I can tell you!"
                sys.exit(1)
            elif arg in ('start', 'stop', 'restart', 'status', 'run'):
                break
            else:
                print "Unknown argument passed.  Please consult --help"
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
        print_help()
        sys.exit(2)