__author__ = 'Steven Ogdahl'

import pymongo
from pymongo import ASCENDING, DESCENDING

#MONGO_CLIENT = 'mongodb://192.168.3.5/'
MONGO_CLIENT = 'mongodb://127.0.0.1/'

def connect_db():
    mongoclient = pymongo.MongoClient(MONGO_CLIENT)
    return mongoclient
