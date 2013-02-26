'''
Created on 07.02.2013

@author: philkraf
'''
import db
import os
from datetime import datetime, timedelta
def findStartDate(siteid,instrumentid):
    session = db.Session()
    ds=session.query(db.Dataset).filter(db.Dataset._site==siteid,db.Dataset._source==instrumentid).order_by(db.Dataset.end.desc()).first()
    if ds:
        return ds.end
    else:
        return None

def finddateGaps(siteid,instrumentid,startdate=None,enddate=None):
    session = db.Session()
    dss = session.query(db.Dataset).filter(db.Dataset._site==siteid,db.Dataset._source==instrumentid
                                           ).order_by('"valuetype","start"')
    if startdate:
        dss=dss.filter(db.Dataset.end>startdate)
    if enddate:
        dss=dss.filter(db.Dataset.start<enddate)
    # Filter for the first occuring valuetype
    ds1 = dss.first()
    if ds1 is None: 
        return [(startdate,enddate)] if startdate and enddate else None
    dss = dss.filter(db.Dataset._valuetype==ds1._valuetype).all()
    # Make start and enddate if not present
    if not startdate:
        startdate=dss[0].start
    if not enddate:
        enddate=dss[-1].end
    if dss:
        res=[]
        # Is there space before the first dataset?
        if startdate<dss[0].start:
            res.append((startdate,dss[0].start))
        # Check for gaps>1 day between datasets 
        for ds1,ds2 in zip(dss[:-1],dss[1:]):
            # if there is a gap between
            if ds1.end - ds2.start >= timedelta(days=1):
                res.append((ds1.end,ds2.start))
        # Is there space after the last dataset
        if enddate>dss[-1].end:
            res.append((dss[-1].end,enddate))
        return res
            
    else:
        return [(startdate,enddate)] if startdate and enddate else None 


        
class ImportStat(object):
    def __init__(self,sum=0.0,min=1e308,max=-1e308,n=0,start=datetime(2100,1,1),end=datetime(1900,1,1)):
        self.sum, self.min,self.max,self.n,self.start,self.end = sum,min,max,n,start,end
    @property
    def mean(self):
        return self.sum / float(self.n)
    def __str__(self):
        d = self.__dict__
        d.update({'mean': self.mean})
        return """Statistics:
        mean    = %(mean)g
        min/max = %(min)g/%(max)g
        n       = %(n)i
        start   = %(start)s
        end     = %(end)s
        """ % d
    def __repr__(self):
        d = self.__dict__
        d.update({'mean': self.mean})
        return repr(d)

    def __jsondict__(self):
        return dict(mean=self.mean,min=self.min,max=self.max,n=self.n,start=self.start,end=self.end)
class ImportAdapter(object):
    def get_statistic(self):
        raise NotImplementedError("Use an implementation class")
    
    def createdatasets(self,comment=''):
        raise NotImplementedError("Use an implementation class")
    
    def submit(self):
        raise NotImplementedError("Use an implementation class")
    
    def __init__(self,filename,user,siteid,instrumentid,startdate,enddate):
        self.filename=filename
        self.name = os.path.basename(self.filename)
        self.user=user
        self.siteid=siteid
        self.instrumentid=instrumentid
        self.startdate=startdate
        self.enddate=enddate
