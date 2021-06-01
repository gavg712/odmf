from odmf.config import conf
from odmf.tools import Path
from odmf import db
import pandas as pd
import os
import numpy as np
import contextlib
import time
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
)

@contextlib.contextmanager
def timeit(name='action'):
    tstart = time.time()
    yield
    d = time.time() - tstart
    print(f'------------ {name} took {d:0.3f} seconds')


session: db.orm.Session = db.Session()
q = session.query

class DbItemGetter:
    def __init__(self, cls):
        self.cls = cls

    def __getitem__(self, item):
        return q(self.cls).get(item)
person = DbItemGetter(db.Person)
ds = DbItemGetter(db.Dataset)

# Set default user
from odmf.webpage import auth
auth.users.load()
auth.users.set_default('philipp')
