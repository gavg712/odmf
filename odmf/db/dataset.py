# -*- coding:utf-8 -*-
'''
Created on 13.07.2012

@author: philkraf
'''
from collections import namedtuple

import sqlalchemy as sql
import sqlalchemy.orm as orm
from .base import Base, Session
from sqlalchemy.schema import ForeignKey
from datetime import datetime
from .dbobjects import newid
import pytz
import typing

import numpy as np
import pandas as pd
from asteval import Interpreter


import importlib

from ..config import conf
from logging import getLogger

logger = getLogger(__name__)

tzberlin = pytz.timezone('Europe/Berlin')
tzwinter = pytz.FixedOffset(60)
tzutc = pytz.utc


class Quality(Base):
    """Denotes the data quality of measurements, from raw to calibrated.
    id: numeric key to the dataquality
    name: Textual representation of the dataquality
    comment: Some additional description
    """
    __tablename__ = 'quality'
    id = sql.Column(sql.Integer, primary_key=True)
    name = sql.Column(sql.String)
    comment = sql.Column(sql.String)

    def __str__(self):
        return self.name

    def __jdict__(self):
        return dict(id=self.id,
                    name=self.name,
                    comment=self.comment)


class ValueType(Base):
    """The value type of datasets shows what is the measured value and unit,
    eg. temperature, Water depth, wind speed etc.
    """
    __tablename__ = 'valuetype'
    id = sql.Column(sql.Integer, primary_key=True)
    name = sql.Column(sql.String)
    unit = sql.Column(sql.String)
    comment = sql.Column(sql.String)
    minvalue = sql.Column(sql.Float)
    maxvalue = sql.Column(sql.Float)

    def __str__(self):
        return f'{self.name} [{self.unit}] ({self.id})'

    def __eq__(self, other):
        return str(self.id).upper() == str(other).upper()

    def __lt__(self, other):
        return str(self.id).upper() < str(other.id).upper()

    def __hash__(self):
        return hash(str(self))

    def records(self):
        session = Session.object_session(self)
        return Record.query(session).filter(Dataset.valuetype == self)

    def __jdict__(self):
        return dict(id=self.id,
                    name=self.name,
                    unit=self.unit,
                    comment=self.comment)

    def inrange(self, value):
        return ((self.minvalue is None or value >= self.minvalue) and
                (self.maxvalue is None or value <= self.maxvalue))


class Dataset(Base):
    """The data set is the central object of the database. It contains metadata and semantics
    for set of records. The data set connects the single observations / measurements with
    the other objects of the databas, like place (site), value type, user etc.

    Dataset is the parent class for other types of datasets, namely Timeseries and TransformedTimeseries,
    possibly more in the future.

    It uses SQLAlchemy's single table inheritance mechanism
    https://docs.sqlalchemy.org/en/14/orm/inheritance.html#single-table-inheritance
    to extend the functionality or the joined table inheritance
     https://docs.sqlalchemy.org/en/14/orm/inheritance.html#joined-table-inheritance

    Datbase fields:
    id: numerical key to the dataset
    name: a short description of the content
    filename: a reference to an existing file in the download area
    start: The first date of the records in the dataset
    end: the date of the last record, or the expected end of the dataset
    site: the location of the dataset in space
    valuetype: the value type of the data set, eg. temperature, water depth etc.
    measured_by: responsible user for this dataset
    quality: the dat quality of the records, eg. raw, checked, calibrated
    source: The data source of the records, an instrument or an external data provider
    calibration_offset, calibration_slope: Values to apply an linear transformation of the records
    comment: Some more details for the dataset


    Backwards references:
    records: A query for records
    """
    __tablename__ = 'dataset'
    id = sql.Column(sql.Integer, primary_key=True)
    name = sql.Column(sql.String, nullable=True)
    filename = sql.Column(sql.String, nullable=True)
    start = sql.Column(sql.DateTime, nullable=True)
    end = sql.Column(sql.DateTime, nullable=True)
    _site = sql.Column("site", sql.Integer, sql.ForeignKey('site.id'))
    site = orm.relationship("Site", primaryjoin='Site.id==Dataset._site',
                            backref=orm.backref('datasets', lazy='dynamic',
                                                # order_by="[Dataset.valuetype.name,sql.desc(Dataset.end)]"
                                                ))
    _valuetype = sql.Column("valuetype", sql.Integer,
                            sql.ForeignKey('valuetype.id'))
    valuetype = orm.relationship("ValueType", backref='datasets')
    _measured_by = sql.Column(
        "measured_by", sql.String, sql.ForeignKey('person.username'))
    measured_by = orm.relationship("Person", backref='datasets',
                                   primaryjoin="Person.username==Dataset._measured_by")
    _quality = sql.Column("quality", sql.Integer,
                          sql.ForeignKey('quality.id'), default=0)
    quality = orm.relationship("Quality")
    _source = sql.Column("source", sql.Integer, sql.ForeignKey(
        'datasource.id'), nullable=True)
    source = orm.relationship("Datasource", backref="datasets")
    calibration_offset = sql.Column(sql.Float, nullable=False, default=0.0)
    calibration_slope = sql.Column(sql.Float, nullable=False, default=1.0)
    comment = sql.Column(sql.String)
    type = sql.Column(sql.String)
    level = sql.Column(sql.Float)
    # TODO: Remove uses_dst
    uses_dst = sql.Column(sql.Boolean, default=False, nullable=False)
    __mapper_args__ = dict(polymorphic_identity=None,
                           polymorphic_on=type)
    access = sql.Column(sql.Integer, default=1, nullable=False)

    timezone = sql.Column(sql.String,
                          default=conf.datetime_default_timezone)
    project = sql.Column(sql.Integer, sql.ForeignKey('project.id'),
                         nullable=True)

    def __str__(self):
        site = self.site.id if self.site else ''
        level = f'{self.level:g} m offset' if self.level is not None else ''
        return (f'ds{self.id or -999:04d}: {self.valuetype} at #{site} {level} with {self.source} '
                f'({self.start or "?"} - {self.end or "?"})').replace("'", r"\'")

    def __jdict__(self):
        return dict(id=self.id,
                    name=self.name,
                    filename=self.filename,
                    start=self.start,
                    end=self.end,
                    site=self.site,
                    valuetype=self.valuetype,
                    measured_by=self.measured_by,
                    quality=self.quality,
                    level=self.level,
                    comment=self.comment,
                    label=self.__str__(),
                    access=self.access)

    def is_timeseries(self):
        return self.type == 'timeseries'

    def is_transformed(self):
        return self.type == 'transformed_timeseries'

    def is_geodataset(self):
        return self.type == 'geodataset'

    @property
    def tzinfo(self):
        if False:
            if self.timezone in pytz.common_timezones:
                return pytz.timezone(self.timezone)
            elif self.timezone.startswith('Fixed/'):
                return pytz.FixedOffset(int(self.timezone.split('/')[1]))
            else:
                return pytz.utc
        else:
            return tzberlin if self.uses_dst else tzwinter

    def localizetime(self, time):
        return self.tzinfo.localize(time)

    def copy(self, id: int):
        """Creates a new dataset without records with the same meta data as this dataset.
        Give a new (unused) id
        """
        cls = type(self)
        return cls(id=id,
                   name=self.name,
                   filename=self.filename,
                   valuetype=self.valuetype,
                   measured_by=self.measured_by,
                   quality=self.quality,
                   source=self.source,
                   calibration_offset=self.calibration_offset,
                   calibration_slope=self.calibration_slope,
                   comment=self.comment,
                   start=self.start,
                   end=self.end,
                   site=self.site,
                   level=self.level,
                   type=self.type,
                   access=self.access,
                   project=self.project,
                   timezone=self.timezone)

    def size(self):
        return 0

    def statistics(self):
        """Calculates mean, stddev and number of records for this data set
        """
        return 0.0, 0.0, 0

    def iterrecords(self, witherrors=False):
        raise NotImplementedError(
            f'{self}(type={self.type}) - data set has no records to iterate. Is the type correct?'
        )

    @property
    def path(self):
        from ..tools import Path as OPath
        if self.filename:
            p = OPath(self.filename)
            if p.exists():
                return p
        return None


def removedataset(*args):
    """Removes a dataset and its records entirely from the database
    !!Handle with care, there will be no more checking!!"""
    session = Session()
    datasets = [session.query(Dataset).get(int(a)) for a in args]
    for ds in datasets:
        dsid = ds.id
        if ds.is_timeseries():
            reccount = ds.records.delete()
            session.commit()
        else:
            reccount = 0
        session.delete(ds)
        session.commit()
        logger.info(f"Deleted ds{dsid:04i} and {reccount} records")


class MemRecord(object):
    def __init__(self, id, dataset, time, value, sample=None, comment=None, is_error=False, rawvalue=None):
        self.id = id
        self.dataset = dataset
        self.time = time
        self.value = value
        self.sample = sample
        self.comment = comment
        self.is_error = is_error
        self.rawvalue = rawvalue


class Record(Base):
    """
    The record holds single measured, quantitative values.

    Database fields:
    id: numeric identifier, new counting for each dataset
    dataset: the owning dataset
    time: the time of the measurement
    value: the value of the measurement
    sample: if the value is from a taken sample, this item can hold the label of the sample
    comment: any additional information
    is_error: if True, the record is marked as error and is not used for analysis
    """
    __tablename__ = 'record'
    id = sql.Column(sql.Integer, primary_key=True)
    _dataset = sql.Column("dataset", sql.Integer,
                          sql.ForeignKey('dataset.id'), primary_key=True)
    dataset = orm.relationship("Timeseries", backref=orm.backref(
        'records', lazy='dynamic'), lazy='joined')
    time = sql.Column(sql.DateTime)
    value = sql.Column(sql.Float)
    sample = sql.Column(sql.String)
    comment = sql.Column(sql.String)
    is_error = sql.Column(sql.Boolean, nullable=False, default=False)

    # CensorCode is from the CUAHSI ODM 1.1 and describes values that are not precisly measured
    # see http://his.cuahsi.org/mastercvreg/cv11.aspx
    # nc is not censored
    censorcode = 'nc'

    __table_args__ = (
        sql.Index('record-dataset-time-index', 'dataset', 'time'),
        sql.Index('record-dataset-index', 'dataset')
    )

    @property
    def calibrated(self):
        """Returns the calibrated value"""
        if self.value is not None:
            return self.dataset.calibration_slope * self.value + self.dataset.calibration_offset
        else:
            return None

    def __str__(self):
        return f'{self.dataset.name}[{self.id}] = {self.value} {self.dataset.valuetype.unit}'

    @classmethod
    def query(cls, session):
        return session.query(cls).select_from(Timeseries).join(Timeseries.records)

    def __jdict__(self):
        return dict(id=self.id,
                    dataset=self.dataset.id,
                    time=self.time,
                    value=self.value,
                    sample=self.sample,
                    comment=self.comment)


transforms_table = sql.Table(
    'transforms', Base.metadata,
    sql.Column('target', sql.Integer, ForeignKey(
        'transformed_timeseries.id'), primary_key=True),
    sql.Column('source', sql.Integer, ForeignKey('dataset.id'), primary_key=True)
)


class Timeseries(Dataset):
    __mapper_args__ = dict(polymorphic_identity='timeseries')
    records: orm.Query

    def split(self, time):
        """Creates a new dataset using copy and assignes all records after
        time to the new dataset. Useful """
        session = self.session()
        next = self.records.filter(
            Record.time >= time, Record.value.isnot(None)).order_by(Record.time).first()
        last = self.records.filter(Record.time <= time, Record.value.isnot(None)).order_by(
            sql.desc(Record.time)).first()
        if not next or not last:
            raise RuntimeError(
                f'Split time {time} is not between two records of {self}')
        self.comment = f'{self.comment} Dataset is splitted at {time} to allow for different calibration'
        dsnew = self.copy(id=newid(Dataset, session))
        self.comment += f'. Other part of the dataset is ds{dsnew.id}\n'
        dsnew.comment += f'. Other part of the dataset is ds{self.id}\n'
        self.end = last.time
        dsnew.start = next.time
        records = self.records.filter(Record.time >= next.time)

        # updates records with orm reference
        for record in records:
            record.dataset = dsnew

        session.commit()
        return self, dsnew


    def statistics(self):
        """
        Return simple statistical description of the timeseries
        :return: mean, stddev, n
        """
        try:  # Try to use sql functions
            f = sql.sql.func
            rv = Record.value
            q = self.session().query(
                f.avg(rv), f.stddev_samp(rv), f.count(rv)
            ).filter_by(_dataset=self.id)
            avg, std, n = q.first()
            avg = avg or 0.0
            std = std or 0.0
            return (
                avg * self.calibration_slope + self.calibration_offset,
                std * self.calibration_slope,
                n
            )

        except (sql.exc.ProgrammingError, sql.exc.OperationalError):
            s = self.asseries()
            if len(s) == 0:
                return 0.0, 0.0, 0
            else:
                return np.mean(s), np.std(s), len(s)

    def findjumps(self, threshold, start=None, end=None):
        """Returns an iterator to find all jumps greater than threshold

        To find "jumps", the records of the dataset are scanned for differences
        between records (ordered by time). If the difference is greater than threshold,
        the later record is returned as a jump
        """
        records = self.records.order_by(Record.time).filter(Record.value.isnot(None), ~Record.is_error).filter(
            Record.time >= (start or self.start)).filter(Record.time <= (end or self.end))
        last = None
        for rec in records:
            if rec.value is not None:
                if threshold == 0.0 or (last and abs(rec.value - last.value) > threshold):
                    yield rec
                last = rec

    def findvalue(self, time):
        """Finds the linear interpolated value for the given time in the record"""
        next = self.records.filter(
            Record.time >= time, Record.value.isnot(None), ~Record.is_error).order_by(Record.time).first()
        last = self.records.filter(
            Record.time <= time, Record.value.isnot(None), ~Record.is_error).order_by(sql.desc(Record.time)).first()
        if next and last:
            dt_next = (next.time - time).total_seconds()
            dt_last = (time - last.time).total_seconds()
            dt = dt_next + dt_last
            if dt < 0.1:
                return next.value, 0.0
            else:
                return (1 - dt_next / dt) * next.value + (1 - dt_last / dt) * last.value, min(dt_last, dt_next)
        elif next:
            return next.value, (next.time - time).total_seconds()
        elif last:
            return last.value, (time - last.time).total_seconds()
        else:
            raise RuntimeError(f'{self} has no records')

    def calibratevalue(self, value):
        """Calibrates a value
        """
        try:
            return value * self.calibration_slope + self.calibration_offset
        except TypeError:
            return None

    def maxrecordid(self):
        """Finds the highest record id for this dataset"""

        # Heavily optimized code for large record tables and an asc-Index of id for the record table
        # See issue #99
        #
        size = self.size()
        sess = self.session()

        # query = self.records.order_by(Record.id).offset(size - 1)
        query = sess.query(Record.id).filter_by(_dataset=self.id).order_by(Record.id).offset(size - 1)
        max_id = query.scalar()
        return max_id

    def addrecord(self, Id=None, value=None, time=None, comment=None, sample=None):
        """Adds a record to the dataset
        Id: id for the recordset, if None, a new id will be created
        value: value of the record
        time: time of the record
        comment: comments for this new record
        """
        value = float(value)
        session = self.session()

        if time is None:
            time = datetime.now()
        Id = Id or self.maxrecordid() + 1

        if (not self.valuetype.inrange(value)):
            raise ValueError(f'RECORD does not fit VALUETYPE: {value:g} {self.valuetype.unit} is out of '
                             f'range for {self.valuetype.name}')
        if not (self.start <= time <= self.end):
            raise ValueError(
                f'RECORD does not fit DATASET: You tried to insert a record for date {time} '
                f'to dataset {self}, which allows only records between {self.start} and {self.end}'
            )

        result = Record(id=Id, time=time, value=value, dataset=self,
                        comment=comment, sample=sample)
        session.add(result)
        return result

    def adjusttimespan(self):
        """
        Adjusts the start and end properties to match the timespan of the records
        """
        Q = self.session().query
        self.start = min(Q(sql.func.min(Record.time)).filter_by(_dataset=self.id).scalar(), self.start)
        self.end = max(Q(sql.func.max(Record.time)).filter_by(_dataset=self.id).scalar(), self.end)

    def size(self):
        return self.records.count()

    def iterrecords(self, witherrors=False, start=None, end=None):
        session = self.session()
        records = session.query(Record).filter(
            Record._dataset == self.id).order_by(Record.time)
        if start:
            records = records.filter(Record.time >= start)
        if end:
            records = records.filter(Record.time <= end)
        records = records.order_by(Record.time)
        if not witherrors:
            records = records.filter(~Record.is_error)
        for r in records:
            yield MemRecord(id=r.id, dataset=r.dataset,
                            time=r.time, value=r.calibrated,
                            sample=r.sample, comment=r.comment,
                            rawvalue=r.value, is_error=r.is_error)

    def asseries(self, start: typing.Optional[datetime] = None, end: typing.Optional[datetime] = None, with_errors=False)->pd.Series:
        """
        Returns a pandas series of the calibrated non-error
        :param start: A start time for the series
        :param end: An end time for the series
        """
        query = self.session().query
        records = query(Record.time, Record.value).filter_by(_dataset=self.id)
        if not with_errors:
            records = records.filter(~Record.is_error)
        if start:
            records = records.filter(Record.time >= start)
        if end:
            records = records.filter(Record.time <= end)

        # Load data from database into dataframe and get the value-Series
        values = pd.read_sql(records.statement, self.session().bind, index_col='time')['value']

        # If no data is present, ensure the right dtype for the empty series
        if values.empty:
            return pd.Series([], index=pd.to_datetime([]), dtype=float)

        # Sort by time ascending
        values.sort_index(inplace=True)
        # Do calibration
        values *= self.calibration_slope
        values += self.calibration_offset
        return values


class TransformedTimeseries(Dataset):
    __tablename__ = 'transformed_timeseries'
    __mapper_args__ = dict(polymorphic_identity='transformed_timeseries')
    id = sql.Column(sql.Integer, sql.ForeignKey(
        'dataset.id'), primary_key=True)
    expression = sql.Column(sql.String)
    latex = sql.Column(sql.String)
    sources = orm.relationship(
        "Timeseries", secondary=transforms_table, order_by="Timeseries.start")

    # An asteval interpreter with minimal functionality
    interpreter = Interpreter(minimal=True, max_statement_length=300)

    def sourceids(self):
        return [s.id for s in self.sources]

    def size(self):
        return self.session().query(Record).filter(Record._dataset.in_(self.sourceids())).count()

    def get_transformation_class(self):
        mod = importlib.import_module(self.expression)

    def asseries(self, start=None, end=None):
        datasets = self.sources
        data = pd.Series()
        if self.expression.startswith('plugin.transformation'):
            # This is a plugin transformation
            # import transformation module
            pass
        else:
            for src in datasets:
                v = src.asseries(start, end)
                v = self.transform(v)
                data = data.append(v)
            data = data.sort_index()
        return data

    def updatetime(self):
        self.start = min(ds.start for ds in self.sources)
        self.end = max(ds.end for ds in self.sources)

    def transform(self, x: pd.Series):
        self.interpreter.symtable['x'] = x.to_numpy()
        result = self.interpreter(self.expression)
        return pd.Series(result, index=x.index, name=str(self))

    def iterrecords(self, witherrors=False, start=None, end=None):
        session = self.session()
        srcrecords = session.query(Record).filter(
            Record._dataset.in_(self.sourceids())).order_by(Record.time)
        if start:
            srcrecords = srcrecords.filter(Record.time >= start)
        if end:
            srcrecords = srcrecords.filter(Record.time <= end)
        if not witherrors:
            srcrecords = srcrecords.filter(~Record.is_error)
        i = 0
        for r in srcrecords:
            i += 1
            yield MemRecord(id=i, dataset=r.dataset, time=r.time,
                            value=self.transform(r.calibrated),
                            sample=r.sample, comment=r.comment,
                            is_error=r.is_error)

    def suitablesources(self):
        session = self.session()
        sourceids = self.sourceids()
        res = session.query(Timeseries).filter(Timeseries.site == self.site,
                                               ~Timeseries.id.in_(sourceids),
                                               )
        if len(self.sources):
            vt = self.sources[0].valuetype
            res = res.filter(Timeseries.valuetype == vt)
        return res

    def statistics(self):
        s = self.asseries()
        if len(s) == 0:
            return 0.0, 0.0, 0
        else:
            return np.mean(s), np.std(s), len(s)



class DatasetGroup(object):
    def __init__(self, datasetids, start=None, end=None):
        self.datasetids = list(datasetids)
        self.start = start
        self.end = end

    def datasets(self, session):
        return session.query(Dataset).filter(Dataset.id.in_(self.datasetids)).order_by(Dataset.start).all()

    def asseries(self, session, name=None):
        datasets = self.datasets(session)
        data = pd.Series(name=name)
        for src in datasets:
            s = src.asseries(self.start, self.end)
            data = data.append(s)
        return data.sort_index()

    def iterrecords(self, session, witherrors):
        datasets = self.datasets(session)
        for ds in datasets:
            for r in ds.iterrecords(witherrors):
                yield r


class DatasetItemGetter:
    """
    Helper class for interactive session for simple dataset access

    dsg = DatasetItemGetter(session)
    ds0 = dsg[0]
    """

    def __init__(self, session):
        self.session = session

    def __getitem__(self, item) -> Dataset:
        return Dataset.get(self.session, item)
