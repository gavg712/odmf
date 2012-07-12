#!/usr/bin/env python
# -*- coding:utf-8 -*-
'''
Created on 13.02.2012

@author: philkraf
'''

import sqlalchemy as sql
import sqlalchemy.orm as orm
from sqlalchemy.ext.declarative import declarative_base

import os.path as op

def abspath(fn):
    "Returns the absolute path to the relative filename fn"
    basepath = op.abspath(op.dirname(__file__))
    normpath = op.normpath(fn)
    return op.join(basepath,normpath)

dbpath = abspath('../data.sqlite').replace('\\','/')
#engine = sql.create_engine('sqlite:///'+dbpath)
def connect():
    import psycopg2
    return psycopg2.connect(user='schwingbach-user',host='fb09-pasig.umwelt.uni-giessen.de',password='VK1:SB0',
                            database='schwingbach')
engine = sql.create_engine('postgresql://',creator=connect)
Session = orm.sessionmaker(bind=engine)

class Base(object):
    """Hooks into SQLAlchemy's magic to make :meth:`__repr__`s."""
    def __repr__(self):
        def reprs():
            for col in self.__table__.c:
                yield col.name, str(getattr(self, col.name))

        def formats(seq):
            for key, value in seq:
                yield '%s=%s' % (key, value)

        args = '(%s)' % ', '.join(formats(reprs()))
        classy = type(self).__name__
        return "<%s%s>" % (classy,args)
    def session(self):
        Session.object_session(self)
    @classmethod
    def query(cls,session):
        return session.query(cls)
    @classmethod
    def get(cls,session,id):
        return session.query(cls).get(id)
        

Base = declarative_base(cls=Base)
metadata=Base.metadata

def primarykey():
    return sql.Column(sql.Integer,primary_key=True)
def stringcol():
    return sql.Column(sql.String)
