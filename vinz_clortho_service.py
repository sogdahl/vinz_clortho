import logging
import signal
import sys
import time
from datetime import datetime, timedelta

from scrapeService.copied_models import Credential, CMRequest

# Seconds to use as a timeout
WAITING_TIMEOUT = 90
USING_TIMEOUT = 600
POLL_INTERVAL = 2


class VCService:
    timestamp_format = '%Y-%m-%d %H:%M:%S'
    min_log_level = logging.WARNING
    logfile = 'vinz_clortho.log'
    IS_RUNNING = False
    SHOULD_BE_RUNNING = False
    PROCESS_STEP = None
    PROCESS_COUNT = 0
    PROCESS_INDEX = 0

    def __init__(self, *args, **kwargs):
        self.min_log_level = kwargs.get('min_log_level', logging.WARNING)
        self.logfile = kwargs.get('logfile', 'vinz_clortho.log')
        if 'WAITING_TIMEOUT' in kwargs:
            global WAITING_TIMEOUT
            WAITING_TIMEOUT = kwargs['WAITING_TIMEOUT']
        if 'USING_TIMEOUT' in kwargs:
            global USING_TIMEOUT
            USING_TIMEOUT = kwargs['USING_TIMEOUT']
        if 'POLL_INTERVAL' in kwargs:
            global POLL_INTERVAL
            POLL_INTERVAL = kwargs['POLL_INTERVAL']
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
            self.log(logging.DEBUG, "Going to sleep for {0} seconds {1}, {2}".format(GRACE_WAIT, self.SHOULD_BE_RUNNING, self.IS_RUNNING))
            time.sleep(GRACE_WAIT)
        self.log(logging.INFO, "Gracefully terminated.")
        sys.exit(0)

    def run(self):
        self.log(logging.INFO, "Running with a polling interval of {0} seconds".format(POLL_INTERVAL))
        self.log(logging.INFO, "Credential waiting timeout is {0} seconds".format(WAITING_TIMEOUT))
        self.log(logging.INFO, "Credential using timeout is {0} seconds".format(USING_TIMEOUT))

        # This is being handled in the daemon context now
        signal.signal(signal.SIGTERM, self.graceful_term)
        self.SHOULD_BE_RUNNING = True

        while self.SHOULD_BE_RUNNING:
            self.IS_RUNNING = True

            self._process_new_requests()
            self._process_cancelled_requests()
            self._process_returned_requests()
            self._process_pending_requests()
            self._process_in_use_credentials()
            self._process_request_queue()

            if self.PROCESS_COUNT > 0:
                self.log(logging.DEBUG, "Done checking credentials to give out for queued requests")

            self.log(logging.DEBUG, "Going to sleep for {0} seconds".format(POLL_INTERVAL))
            self.IS_RUNNING = False
            time.sleep(POLL_INTERVAL)

        self.log(logging.DEBUG, "Got out of main 'while' loop")


    def _process_new_requests(self):
        new_requests = CMRequest.objects.filter(status=CMRequest.SUBMITTED)
        self.PROCESS_STEP = "New Requests"
        self.PROCESS_COUNT = new_requests.count()
        self.PROCESS_INDEX = 0
        if self.PROCESS_COUNT > 0:
            self.log(logging.DEBUG, "Processing {0} new requests".format(self.PROCESS_COUNT))
            self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in new_requests])))
        for new_request in new_requests:
            self.PROCESS_INDEX += 1
            credentials = Credential.objects.filter(key=new_request.key)

            # If we didn't find any credentials, then error out this request
            if len(credentials) == 0:
                new_request.status = CMRequest.NO_SUCH_KEY
                self.log(logging.ERROR, "No such key found: {0}".format(new_request.key), new_request)
                new_request.save()
                continue

            new_request.status = CMRequest.QUEUING
            self.log(logging.INFO, "Putting into queue", new_request)
            new_request.save()
        if self.PROCESS_COUNT > 0:
            self.log(logging.DEBUG, "Done processing new requests")


    def _process_cancelled_requests(self):
        # This is mainly a formality, but just mark all the ones that are a
        # status of CANCEL to CANCELED instead.  This indicates that the
        # server acknowledged the order to cancel
        cancel_requests = CMRequest.objects.\
            filter(status=CMRequest.CANCEL)
        self.PROCESS_STEP = "Cancel Requests"
        self.PROCESS_COUNT = cancel_requests.count()
        self.PROCESS_INDEX = 0
        if self.PROCESS_COUNT > 0:
            self.log(logging.DEBUG, "Processing {0} cancel requests".format(self.PROCESS_COUNT))
            self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in cancel_requests])))
        for cancel_request in cancel_requests:
            self.PROCESS_INDEX += 1
            cancel_request.status = CMRequest.CANCELED
            self.log(logging.INFO, "Canceled by client", cancel_request)
            cancel_request.save()
        if self.PROCESS_COUNT > 0:
            self.log(logging.DEBUG, "Done processing cancel requests")


    def _process_returned_requests(self):
        returned_credentials = CMRequest.objects.\
            filter(status=CMRequest.RETURNED)
        self.PROCESS_STEP = "Returned Credentials"
        self.PROCESS_COUNT = returned_credentials.count()
        self.PROCESS_INDEX = 0
        if self.PROCESS_COUNT > 0:
            self.log(logging.DEBUG, "Processing {0} returned credentials".format(self.PROCESS_COUNT))
            self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in returned_credentials])))
        for returned_credential in returned_credentials:
            self.PROCESS_INDEX += 1
            returned_credential.status = CMRequest.COMPLETED
            returned_credential.checkin_timestamp = datetime.now()
            self.log(logging.INFO, "CredentialId {0} returned by client (Elapsed: {1:.1f}s)".format(
                returned_credential.credential.id,
                (returned_credential.checkin_timestamp - returned_credential.checkout_timestamp).total_seconds()
            ), returned_credential)
            returned_credential.save()
        if self.PROCESS_COUNT > 0:
            self.log(logging.DEBUG, "Done processing returned credentials")


    def _process_pending_requests(self):
        pending_credentials = CMRequest.objects.\
            filter(status=CMRequest.GIVEN_OUT)
        self.PROCESS_STEP = "Pending Credentials"
        self.PROCESS_COUNT = pending_credentials.count()
        self.PROCESS_INDEX = 0
        if self.PROCESS_COUNT > 0:
            self.log(logging.DEBUG, "Testing {0} given out credentials for time-out".format(self.PROCESS_COUNT))
            self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in pending_credentials])))
        for pending_credential in pending_credentials:
            self.PROCESS_INDEX += 1
            if (datetime.now() - pending_credential.checkout_timestamp).total_seconds() > WAITING_TIMEOUT:
                pending_credential.status = CMRequest.TIMED_OUT_WAITING
                self.log(logging.WARNING, "Timed out waiting for client to receive credentials", pending_credential)
                pending_credential.save()
        if self.PROCESS_COUNT > 0:
            self.log(logging.DEBUG, "Done testing given-out credentials for time-out")


    def _process_in_use_credentials(self):
        in_use_credentials = CMRequest.objects.\
            filter(status__in=[CMRequest.IN_USE, CMRequest.CANCEL], checkout_timestamp__isnull=False)
        self.PROCESS_STEP = "In-use Credentials"
        self.PROCESS_COUNT = in_use_credentials.count()
        self.PROCESS_INDEX = 0
        if self.PROCESS_COUNT > 0:
            self.log(logging.DEBUG, "Testing {0} in-use credentials for time-out".format(self.PROCESS_COUNT))
            self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in in_use_credentials])))
        for in_use_credential in in_use_credentials:
            self.PROCESS_INDEX += 1
            if (datetime.now() - in_use_credential.checkout_timestamp).total_seconds() > USING_TIMEOUT:
                in_use_credential.status = CMRequest.TIMED_OUT_USING
                self.log(logging.WARNING, "Timed out waiting for client to return credentials", in_use_credential)
                in_use_credential.save()
        if self.PROCESS_COUNT > 0:
            self.log(logging.DEBUG, "Done testing in-use credentials for time-out")


    def _process_request_queue(self):
        # This is the meat of the big loop.  This section is the one that
        # will be doling out the credentials on a first-come, first-serve
        # basis, with priority overriding that.
        queued_requests = CMRequest.objects.\
            filter(status=CMRequest.QUEUING).\
            order_by('-priority', 'submission_timestamp', 'id')
        self.PROCESS_STEP = "Queued Requests"
        self.PROCESS_COUNT = queued_requests.count()
        self.PROCESS_INDEX = 0
        if self.PROCESS_COUNT > 0:
            self.log(logging.DEBUG, "Checking credentials to give out for {0} queued requests".format(
                self.PROCESS_COUNT)
            )
            self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(r.id) for r in queued_requests])))
        for queued_request in queued_requests:
            self.PROCESS_INDEX += 1
            available_credentials = Credential.objects.filter(key=queued_request.key)
            if available_credentials.count() > 0:
                self.log(logging.DEBUG, "Testing {0} available credentials for queued request".format(
                    available_credentials.count()
                ), queued_request)
                self.log(logging.DEBUG, "Ids: {0}".format(', '.join([str(c.id) for c in available_credentials])))
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

                # If (A OR B) AND (X OR Y)
                # A: we're allowed to give out an infinite number of checkouts
                # -or-
                # B: we've give out fewer credentials than we're allowed to
                # --and--
                # X: there's no throttling enabled for this credential
                # -or-
                # Y: this credential isn't being throttled (see above)
                # Then we're allowed to give out the credential
                if (available_credential.max_checkouts == 0 or
                        in_use_credentials < available_credential.max_checkouts) and \
                        (available_credential.throttle_timespan == 0 or credential_frequency == 0):
                    # We found a credential available to be used! Yay!
                    queued_request.credential = available_credential
                    queued_request.status = CMRequest.GIVEN_OUT
                    queued_request.checkout_timestamp = datetime.now()
                    self.log(
                        logging.INFO, 
                        "Assigning CredentialId: {0} to client (waited {1:.1f}s)".format(
                            available_credential.id,
                            (queued_request.checkout_timestamp - queued_request.submission_timestamp).total_seconds()
                        ), 
                        queued_request
                    )
                    queued_request.save()
                    break
