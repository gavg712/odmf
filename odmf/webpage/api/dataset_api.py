import io

import cherrypy
import datetime
from traceback import format_exc as traceback
from contextlib import contextmanager

import pandas as pd

from .. import lib as web
from ..auth import users, expose_for, group, has_level
from ... import db
from ...config import conf
from . import BaseAPI, get_help

@cherrypy.popargs('dsid')
class DatasetAPI(BaseAPI):
    """
    Provides an REST API to datasets

    Usages:

    :/api/dataset: Returns a list of existing dataset ids
    :/api/dataset/1: Returns the dataset metadata as json of ds1
    :/api/dataset/new: Creates a new dataset using POST or PUT data.
    :/api/dataset/addrecord: Adds a record to a dataset using PUT data
                             in the form ``{dsid: 1, value:2.0, time:2019-05-03T12:02}``

    """
    exposed = True
    url = conf.root_url + '/api/dataset'

    @staticmethod
    def parse_id(dsid: str) -> int:
        if dsid[:2] != 'ds':
            raise web.APIError(404, f'Dataset id does not start with ds. Got {dsid}')
        try:
            return int(dsid[2:])
        except (TypeError, ValueError):
            raise web.APIError(404, f'Last part of dataset id is not a number. Got {dsid}')

    @staticmethod
    @contextmanager
    def get_dataset(dsid: str, check_access=True) -> db.Dataset:
        dsid = DatasetAPI.parse_id(dsid)
        with db.session_scope() as session:
            ds = session.query(db.Dataset).get(dsid)
            if not ds:
                raise web.APIError(404, f'ds{dsid} does not exist')
            elif check_access and not has_level(ds.access):
                raise web.APIError(403, f'ds{dsid} is protected. Need a higher access level')
            else:
                yield ds


    @expose_for(group.guest)
    @web.method.get
    @web.mime.json
    def index(self, dsid=None):
        """
        Returns a json representation of a datasetid
        :param dsid: The Dataset id
        :return: json representation of the dataset metadata
        """

        if dsid is None:
            res = get_help(self, self.url)
            res[f'{self.url}/[n]'] = f"A dataset with the id [n]. See {self.url}/list method"
            return web.json_out(res)
        with self.get_dataset(dsid, False) as ds:
            return web.json_out(ds)

    @expose_for(group.guest)
    @web.mime.json
    def records(self, dsid):
        """
        Returns all records (uncalibrated) for a dataset as json
        """
        with self.get_dataset(dsid) as ds:
            return web.json_out(ds.records.all())

    @expose_for(group.guest)
    @web.mime.json
    def values(self, dsid, start=None, end=None):
        """
        NOT TESTED! Returns the calibrated values for a dataset
        :param dsid: The dataset id
        :param start: A start time
        :param end: an end time
        :return: JSON list of time/value pairs
        """
        start = web.parsedate(start, False)
        end = web.parsedate(end, False)
        with self.get_dataset(dsid) as ds:
            series = ds.asseries(start, end)
            return series.to_json().encode('utf-8')

    @expose_for(group.guest)
    @web.method.get
    @web.mime.binary
    def values_parquet(self, dsid, start=None, end=None):
        """
        Returns the calibrated values for a dataset
        :param dsid: The dataset id
        :param start: A start time to crop the data
        :param end: an end time to crop the data
        :return: parquet data stream, to be used by Python or R
        """
        start = web.parsedate(start, False)
        end = web.parsedate(end, False)
        with self.get_dataset(dsid) as ds:
            series: pd.Series = ds.asseries(start, end)
            df = pd.DataFrame({'value': series})
            df.reset_index(inplace=True)
            buf = io.BytesIO()
            df.to_parquet(buf)
            return buf.getvalue()


    @expose_for()
    @web.method.get
    @web.mime.json
    def list(self):
        """
        Returns a JSON list of all available dataset url's
        """
        res = []
        with db.session_scope() as session:
            return web.json_out([
                f'{self.url}/ds{ds}'
                for ds, in sorted(session.query(db.Dataset.id))
            ])


    @expose_for(group.editor)
    @web.method.post_or_put
    @web.json_in()
    def new(self):
        """
        Creates a new dataset. Possible data fields:
        measured_by, valuetype, quality, site, source, filename,
        name, comment, project, timezone, level, etc.

        """

        kwargs = cherrypy.request.json
        with db.session_scope() as session:
            try:
                pers = session.query(db.Person).get(kwargs.get('measured_by'))
                vt = session.query(db.ValueType).get(kwargs.get('valuetype'))
                q = session.query(db.Quality).get(kwargs.get('quality'))
                s = session.query(db.Site).get(kwargs.get('site'))
                src = session.query(db.Datasource).get(kwargs.get('source'))

                ds = db.Timeseries()
                # Get properties from the keyword arguments kwargs
                ds.site = s
                ds.filename = kwargs.get('filename')
                ds.name = kwargs.get('name')
                ds.comment = kwargs.get('comment')
                ds.measured_by = pers
                ds.valuetype = vt
                ds.quality = q

                if kwargs.get('project') == '0':
                    ds.project = None
                else:
                    ds.project = kwargs.get('project')

                ds.timezone = kwargs.get('timezone')

                if src:
                    ds.source = src
                if 'level' in kwargs:
                    ds.level = web.conv(float, kwargs.get('level'))
                # Timeseries only arguments
                if ds.is_timeseries():
                    if kwargs.get('start'):
                        ds.start = datetime.datetime.strptime(
                            kwargs['start'], '%d.%m.%Y')
                    if kwargs.get('end'):
                        ds.end = datetime.datetime.strptime(kwargs['end'], '%d.%m.%Y')
                    ds.calibration_offset = web.conv(
                        float, kwargs.get('calibration_offset'), 0.0)
                    ds.calibration_slope = web.conv(
                        float, kwargs.get('calibration_slope'), 1.0)
                    ds.access = web.conv(int, kwargs.get('access'), 1)
                # Transformation only arguments
                if ds.is_transformed():
                    ds.expression = kwargs.get('expression')
                    ds.latex = kwargs.get('latex')
                # Save changes
                session.commit()
                cherrypy.response.status = 200
                return f'ds{ds.id}'.encode()

            except Exception as e:
                # On error render the error message
                raise web.APIError(400, 'Creating new timeseries failed') from e

    @expose_for(group.editor)
    @web.method.post_or_put
    def addrecord(self, dsid, value, time,
                       sample=None, comment=None, recid=None):
        """
        Adds a single record to a dataset

        JQuery usage: $.put('/api/dataset/addrecord', {dsid=1000, value=1.5, time='2019-02-01T17:00:00'}, ...);

        :param dsid: Dataset id
        :param value: Value to add
        :param time: Time of measurement
        :param sample: A link to a sample name (if present)
        :param comment: A comment about the measurement (if needed)
        :param recid: A record id (will be created if missing)
        :return: The id of the new record
        """
        time = web.parsedate(time)
        with db.session_scope() as session:
            try:
                dsid = self.parse_id(dsid)
                ds = session.query(db.Timeseries).get(dsid)
                if not ds:
                    return 'Timeseries ds:{} does not exist'.format(dsid)
                new_rec = ds.addrecord(Id=recid, time=time, value=value, comment=comment, sample=sample)
                return str(new_rec.id).encode('utf-8')
            except Exception as e:
                raise web.APIError(400, 'Could not add record') from e


    @expose_for(group.editor)
    @web.method.post_or_put
    @web.mime.json
    def addrecords_parquet(self):
        """
        Expects a table in the apache arrow format to import records to existing datasets. Expected column names:
        dataset, id, time, value [,sample, comment, is_error]
        """
        import pandas as pd
        instream = cherrypy.request.body

        # Load dataframe
        try:
            df = pd.read_parquet(instream)
            df = df[~df.value.isna()]
        except Exception as e:
            raise web.APIError(400, 'Incoming data is not in the Apache Arrow format') from e

        # Check columns
        if 'id' not in df.columns:
            df['id'] = df['index']
        if 'is_error' not in df.columns:
            df['is_error'] = False
        if not all(cname in df.columns for cname in ['dataset', 'id', 'time', 'value']):
            raise web.APIError(400, 'Your table misses one or more of the columns dataset, id, time, value [,sample, comment]')

        # remove unused columns
        for c in list(df.columns):
            if c not in ['dataset', 'id', 'time', 'value', 'sample', 'comment', 'is_error']:
                del df[c]

        with db.session_scope() as session:

            # Check datasets
            datasets = set(int(id) for id in df.dataset.unique())
            all_db = set(v[0] for v in session.query(db.Dataset.id))
            missing = datasets - all_db
            if missing:
                raise web.APIError(400, 'Your table contains records for not existing dataset-ids: ' + ', '.join(str(ds) for ds in missing))

            # Alter id and timeranges
            for dsid in datasets:
                ds: db.Timeseries = session.query(db.Dataset).get(dsid)
                maxrecordid = ds.maxrecordid()
                df_ds = df[df.dataset == dsid]
                if df_ds.index.min() < maxrecordid:
                    df_ds.index += maxrecordid - df[df.dataset == ds].index.min() + 1
                ds.start = min(ds.start, df_ds['time'].min().to_pydatetime())
                ds.end = max(ds.end, df_ds['time'].max().to_pydatetime())

            # commit to db
            conn = session.connection()
            try:
                df.to_sql('record', conn, if_exists='append', index=False, method='multi', chunksize=1000)
            except Exception as e:
                raise web.APIError(500, 'Could not append dataframe') from e
            return web.json_out(dict(status='success', records=len(df), datasets=list(datasets)))


    @web.json_in()
    @expose_for(group.editor)
    @web.method.post_or_put
    def addrecords(self):
        """
        TODO: finish function
        Adds a couple of records from a larger JSON list
        JQuery usage:
            $.put('/api/dataset/addrecord',
                  [{dsid=1000, value=1.5, time='2019-02-01T17:00:00'},
                   {dsid=1000, value=2.5, time='2019-02-01T17:00:05'},
                   ...
                  ], ...);
        """
        data = cherrypy.request.json
        if not type(data) is list:
            data = [data]
        warnings = []
        with db.session_scope() as session:
            dataset = None
            for rec in data:
                dsid = rec.get('dsid') or rec.get('dataset') or rec.get('dataset_id')
                if not dsid:
                    warnings.append(f'{rec} does not reference a valid dataset '
                                    f'(allowed keywords are dsid, dataset and dataset_id)')
                if not dataset or dataset.id != dsid:
                    # load dataset from db
                    dataset = session.query(db.Dataset).get(dsid)
                else:
                    ...  # reuse last dataset
                if not dataset:
                    warnings.append(f'ds{dsid} does not exist')
                # get value, time, sample, comment and recid

    @expose_for()
    @web.method.get
    @web.mime.json
    def statistics(self, dsid):
        """
        Returns a json object holding the statistics for the dataset
        (is loaded by page using ajax)
        """
        with self.get_dataset(dsid, False) as ds:
            # Get statistics
            mean, std, n = ds.statistics()
            if not n:
                mean = 0.0
                std = 0.0
            # Convert to json
            return web.json_out(dict(mean=mean, std=std, n=n))

