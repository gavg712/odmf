# -*- coding: utf-8 -*-

'''
Created on 13.07.2012

@author: philkraf
'''
from .. import lib as web
from ... import db
from traceback import format_exc as traceback
from glob import glob
import os.path as op
from ..auth import expose_for, group
from io import BytesIO
from ...db import projection as proj
from ..preferences import Preferences
from ...config import conf


@web.expose
@web.show_in_nav_for(1, 'map-marker-alt')
class SitePage:
    url = conf.root_url + '/site/'
    @expose_for(group.guest)
    def default(self, actualsite_id=None, error=''):
        """
        Shows the page for a single site.
        """
        session = db.Session()
        pref = Preferences()

        if not actualsite_id:
            actualsite_id = pref['site']
        else:
            pref['site'] = actualsite_id

        try:
            actualsite = session.query(db.Site).get(int(actualsite_id))
            datasets = actualsite.datasets.join(db.ValueType)
            datasets = datasets.order_by(
                db.ValueType.name, db.sql.desc(db.Dataset.end))
        except:
            error = traceback()
            datasets = []
            actualsite = None
        result = web.render('site.html', actualsite=actualsite, error=error,
                            datasets=datasets, icons=self.geticons()
                            ).render()
        session.close()
        return result

    @expose_for(group.editor)
    def new(self, lat=None, lon=None, name=None, error=''):
        session = db.Session()
        try:
            actualsite = db.Site(id=db.newid(db.Site, session),
                                 lon=web.conv(float, lon) or 8.55, lat=web.conv(float, lat) or 50.5,
                                 name=name or '<enter site name>')
        except:
            error = traceback()
            actualsite = None
        result = web.render('site.html', actualsite=actualsite, error=error,
                            datasets=actualsite.datasets, icons=self.geticons()
                            ).render()
        session.close()
        return result

    @expose_for(group.editor)
    @web.method.post
    def saveitem(self, **kwargs):
        try:
            siteid = web.conv(int, kwargs.get('id'), '')
        except:
            raise web.redirect(f'{self.url}/{siteid}', error=traceback())
        if 'save' in kwargs:
            with db.session_scope() as session:
                try:
                    site = session.query(db.Site).get(int(siteid))
                    if not site:
                        site = db.Site(id=int(siteid))
                        session.add(site)
                    site.lon = web.conv(float, kwargs.get('lon'))
                    site.lat = web.conv(float, kwargs.get('lat'))
                    if None in (site.lon, site.lat):
                        raise web.redirect(f'../{siteid}', error='The site has no coordinates')
                    if site.lon > 180 or site.lat > 180:
                        site.lat, site.lon = proj.UTMtoLL(
                            23, site.lat, site.lon, '32N')

                    site.name = kwargs.get('name')
                    site.height = web.conv(float, kwargs.get('height'))
                    site.icon = kwargs.get('icon')
                    site.comment = kwargs.get('comment')
                except:
                    raise web.redirect(f'{self.url}/{siteid}', error=traceback())
        raise web.redirect(f'{self.url}/{siteid}')

    @expose_for()
    @web.mime.json
    def getinstalledinstruments(self):
        with db.session_scope() as session:
            inst = [
                inst for inst in session.query(db.Datasource)
                if inst.sites.count()
            ]
            return web.json_out(sorted(inst))

    @expose_for()
    @web.mime.json
    def getinstruments(self):
        with db.session_scope() as session:
            inst = session.query(db.Datasource).all()
            return web.json_out(sorted(inst))

    @expose_for(group.editor)
    def addinstrument(self, siteid, instrumentid, date=None):
        if not instrumentid:
            raise web.redirect(conf.root_url + '/instrument/new')
        with db.session_scope() as session:

            error = ''
            try:
                date = web.parsedate(date)
                site = session.query(db.Site).get(int(siteid))
                instrument = session.query(db.Datasource).get(int(instrumentid))
                pot_installations = session.query(db.Installation)
                pot_installations = pot_installations.filter(
                    db.Installation.instrument == instrument, db.Installation.site == site)
                pot_installations = pot_installations.order_by(
                    db.sql.desc(db.Installation.id))
                if pot_installations.count():
                    instid = pot_installations.first().id
                else:
                    instid = 0
                inst = db.Installation(site, instrument, instid + 1, date)
                session.add(inst)
                session.commit()
            except:
                return traceback()

    @expose_for(group.editor)
    def removeinstrument(self, siteid, instrumentid, installationid, date=None):
        session = db.Session()
        error = ''
        try:
            date = web.parsedate(date)
            site = session.query(db.Site).get(int(siteid))
            instrument = session.query(db.Datasource).get(int(instrumentid))
            pot_installations = session.query(db.Installation)
            pot_installations = pot_installations.filter(
                db.Installation.instrument == instrument, db.Installation.site == site)
            pot_installations = pot_installations.order_by(
                db.sql.desc(db.Installation.id))
            inst = pot_installations.filter_by(id=int(installationid)).first()
            if inst:
                inst.removedate = date
                session.commit()
            else:
                error = 'Could not find installation to remove (siteid=%s,instrument=%s,id=%s)' % (
                    siteid, instrumentid, installationid)
                session.rollback()
        except:
            error = traceback()
            session.rollback()
        finally:
            session.close()
        return error

    @expose_for()
    @web.mime.json
    def json(self):
        with db.session_scope() as session:
            return web.json_out(session.query(db.Site).order_by(db.Site.id).all())

    @expose_for()
    @web.mime.kml
    def kml(self, sitefilter=None):
        session = db.Session()
        query = session.query(db.Site)
        if filter:
            query = query.filter(sitefilter)
        stream = web.render('sites.xml', sites=query.all(),
                            actid=0, descriptor=SitePage.kml_description)
        result = stream.render('xml')
        session.close()
        return result

    @classmethod
    def kml_description(cls, site):
        host = "http://fb09-pasig.umwelt.uni-giessen.de:8081"
        text = [site.comment,
                '<a href="%s/site/%s">edit...</a>' % (host, site.id)]
        if site.height:
            text.insert(0, '%0.1f m NN' % site.height)
        text.append('<h3>Logbuch:</h3>')
        for log in site.logs:
            content = dict(date=web.formatdate(log.time),
                           user=log.user, msg=log.message, host=host, id=log.id)
            text.append(
                '<li><a href="%(host)s/log/%(id)s">%(date)s, %(user)s: %(msg)s</a></li>' % content)
        text.append('<h3>Datens&auml;tze:</h3>')
        for ds in site.datasets:
            content = dict(id=ds.id, name=ds.name, start=web.formatdate(
                ds.start), end=web.formatdate(ds.end), vt=ds.valuetype, host=host)
            text.append(
                '<li><a href="%(host)s/dataset/%(id)s">%(name)s, %(vt)s (%(start)s-%(end)s)</a></li>' % content)
        return '<br/>'.join(text)

    def geticons(self):
        path = conf.abspath('media/mapicons')
        return [op.basename(p) for p in glob(op.join(path, '*.png')) if not op.basename(p) == 'selection.png']

    @expose_for(group.guest)
    @web.mime.json
    def with_instrument(self, instrumentid):
        with db.session_scope() as session:
            sites = []
            inst = session.query(db.Datasource).get(int(instrumentid))
            return web.json_out(sorted(set(i.site for i in inst.sites)))

    @expose_for(group.logger)
    @web.mime.csv
    def sites_csv(self):
        session = db.Session()
        query = session.query(db.Site).order_by(db.Site.id)
        st = BytesIO()
        # TODO: Py3 encoding
        st.write(
            '"ID","long","lat","x_proj","y_proj","height","name","comment"\n'.encode('latin1'))
        for s in query:
            c = s.comment.replace('\r', '').replace('\n', ' / ')
            h = '%0.3f' % s.height if s.height else ''
            Z, x, y = s.as_UTM()
            st.write(('%s,%f,%f,%0.1f,%0.1f,%s,"%s","%s"\n' %
                      (s.id, s.lon, s.lat, x, y, h, s.name, c)).encode('latin1'))
        session.close()
        return st.getvalue()
