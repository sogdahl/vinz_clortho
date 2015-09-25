__author__ = 'Steven Ogdahl'

# You must call patch_all() *before* importing any other modules
#from gevent import monkey
#monkey.patch_all()

import bson.objectid
from datetime import datetime, timedelta
import json
from flask import Flask, request, session, url_for, redirect, render_template, abort, g, flash
import pymongo
import time

from models import *
import mongo

#DEBUG = True

class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        elif isinstance(o, bson.objectid.ObjectId):
            return str(o)
        return json.JSONEncoder.default(self, o)

app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_envvar('VINZ_CLORTHO_SETTINGS', silent=True)

def connect_db():
    return mongo.connect_db()

def init_db():
    db = get_db()
    # Do any initialization stuff here

def get_client():
    if not hasattr(g, 'mongo_client'):
        g.mongo_client = connect_db()
    return g.mongo_client

def get_db():
    return get_client().vinz_clortho

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'mongo_client'):
        g.mongo_client.close()


@app.route('/credential/add', methods=['POST'])
def add_credential():
    db = get_db()
    result = db.credential.insert_one({
        'key': request.json['key'],
        'username': request.json['username'],
        'password': request.json['password'],
        'max_checkouts': int(request.json['max_checkouts']),
        'throttle_seconds': int(request.json['throttle_seconds'])
    })
    return JSONEncoder().encode(result.inserted_id)

@app.route('/credential/list', methods=['GET'])
def list_credentials():
    db = get_db()
    credentials = []
    filter = {}
    if 'key' in request.args:
        filter['key'] = request.args['key']
    sort_by = [
        ('key', mongo.ASCENDING),
        ('_id', mongo.ASCENDING)
    ]
    if 'sort_by' in request.args:
        if request.args['sort_by'].startswith('-'):
            s_key = (request.args['sort_by'][1:], mongo.DESCENDING)
        else:
            s_key = (request.args['sort_by'], mongo.ASCENDING)
        sort_by.insert(0, s_key)
    for c in db.credential.find(filter=filter, sort=sort_by):
        c['db'] = db
        cred = Credential(**c)
        credentials.append(cred.to_dict())
    return JSONEncoder().encode(credentials)


@app.route('/credential/request/list', methods=['GET'])
def list_credential_requests():
    db = get_db()
    requests = []
    filter = {}
    if 'pending' in request.args:
        filter['status'] = {
            '$in': [
                CMRequest.SUBMITTED,
                CMRequest.QUEUING,
                CMRequest.CANCEL,
                CMRequest.GIVEN_OUT
            ]
        }
    sort_by = [
        ('priority', mongo.DESCENDING),
        ('submission_timestamp', mongo.ASCENDING),
        ('_id', mongo.ASCENDING)
    ]
    for c in db.cm_request.find(filter=filter, sort=sort_by):
        c['db'] = db
        cred = CMRequest(**c)
        requests.append(cred.to_dict())
    return JSONEncoder().encode(requests)


@app.route('/credential/request/<key>', methods=['GET'])
def credentials_request(key):
    db = get_db()
    try:
        priority = int(request.args.get('priority', 10))
    except:
        priority = 10
    result = db.cm_request.insert_one({
        'key': key,
        'client': '{0} :: {1}'.format(request.remote_addr, request.url),
        'submission_timestamp': datetime.now(),
        'priority': priority,
        'status': CMRequest.SUBMITTED
    })

    return credentials_ticket_status(str(result.inserted_id))


@app.route('/credential/status/<ticket>', methods=['GET'])
def credentials_ticket_status(ticket):
    poll = False
    poll_interval = 5
    poll_timeout = 60
    if request.args.get('poll', '').lower() in ('1', 'yes', 'true', 'y'):
        poll = True
        try:
            poll_interval = int(request.args.get('poll_interval', 5))
        except:
            pass
        try:
            poll_timeout = int(request.args.get('poll_timeout', 60))
        except:
            pass

    response_data = {
        'key': '',
        'ticket': ticket,
        'status': 0,
    }

    db = get_db()
    id = bson.objectid.ObjectId(ticket)
    cm_request = CMRequest.find_one(db, filter=id)

    if cm_request:
        start_time = datetime.now()
        while True:

            if cm_request.status == CMRequest.GIVEN_OUT:
                cm_request.update(status=CMRequest.IN_USE)

            response_data['key'] = cm_request.key
            response_data['status'] = cm_request.status
            response_data['submitted'] = cm_request.submission_timestamp

            if cm_request.checkout_timestamp:
                response_data['checkout'] = cm_request.checkout_timestamp
            if cm_request.checkin_timestamp:
                response_data['checkin'] = cm_request.checkin_timestamp

            # Credentials should only be returned if the status is proper
            if cm_request.credential and cm_request.status in (
                    CMRequest.GIVEN_OUT,
                    CMRequest.IN_USE
                ):
                credential = Credential.find_one(db, filter={'_id': cm_request.credential})
                response_data['username'] = credential.username
                response_data['password'] = credential.password

            if datetime.now() - start_time > timedelta(seconds=poll_timeout):
                break

            elif poll and cm_request.status in (
                    CMRequest.SUBMITTED,
                    CMRequest.QUEUING
                ):
                time.sleep(poll_interval)
                cm_request = CMRequest.find_one(db, filter=id)
                if not cm_request:
                    break

            else:
                break

    return JSONEncoder().encode(response_data)


@app.route('/credential/release/<ticket>', methods=['GET'])
def credentials_release(ticket):
    db = get_db()
    id = bson.objectid.ObjectId(ticket)
    cm_req = db.cm_request.find_one(filter=id)

    if cm_req:
        cm_request = CMRequest(db=db, **cm_req)

        if cm_request.status in (
            CMRequest.IN_USE,
            CMRequest.GIVEN_OUT
        ):
            cm_request.update(status=CMRequest.RETURNED)

        elif cm_request.status in (
            CMRequest.QUEUING,
            CMRequest.SUBMITTED
        ):
            cm_request.update(status=CMRequest.CANCEL)

    return credentials_ticket_status(ticket)


@app.route('/')
def hello_world():
    return 'Hello World!'