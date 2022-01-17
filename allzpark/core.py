
import os
import time
import logging
from itertools import groupby
from bson.objectid import ObjectId
from pymongo import MongoClient
from pymongo.database import Database as MongoDatabase
from pymongo.collection import Collection as MongoCollection
from dataclasses import dataclass


log = logging.getLogger(__name__)


@dataclass
class Project:
    name: str
    is_active: bool
    coll: MongoCollection
    _doc: dict

    def doc(self):
        return self._doc

    def iter_tools(self):
        pass

    def iter_assets(self):
        """Iter assets in breadth first manner

        If `silo` exists, silos will be iterated first as Asset.

        :return: Asset item iterator
        :rtype: collections.Iterator[Asset]
        """
        return iter_avalon_assets(self)

    def user_role(self):
        pass


@dataclass
class Asset:
    name: str
    project: Project
    parent: "Asset" or None
    is_silo: bool
    is_hidden: bool
    coll: MongoCollection
    _doc: dict or None

    def iter_tools(self):
        pass

    def iter_tasks(self):
        pass


@dataclass
class Task:
    name: str
    project: Project
    asset: Asset
    coll: MongoCollection
    _doc: dict

    def iter_tools(self):
        pass


class AvalonMongo(object):
    """Avalon MongoDB connector
    """
    def __init__(self, uri, only_active=True, timeout=1000):
        """
        :param str uri: MongoDB URI string
        :param bool only_active: Skip inactive projects, default True
        :param int timeout: MongoDB connection timeout, default 1000
        """
        db_avalon = os.getenv("AVALON_DB", "avalon")
        conn = MongoClient(uri, serverSelectionTimeoutMS=timeout)

        self._uri = uri
        self._conn = conn
        self._timeout = timeout
        self._db_avalon = conn[db_avalon]
        self._only_active = only_active

    def ping(self, retry=3):
        """Test database connection with retry

        :param int retry: Max retry times, default 3
        :return: None
        :raises IOError: If not able to connect in given retry times
        """
        for i in range(retry):
            try:
                t1 = time.time()
                self._conn.server_info()

            except Exception:
                log.error("Retrying..[%d]" % i)
                time.sleep(1)
                self._timeout *= 1.5

            else:
                break

        else:
            raise IOError(
                "ERROR: Couldn't connect to %s in less than %.3f ms"
                % (self._uri, self._timeout)
            )

        log.info(
            "Connected to %s, delay %.3f s" % (self._uri, time.time() - t1)
        )

    def iter_projects(self):
        """Iter projects

        :return: Project item iterator
        :rtype: collections.Iterator[Project]
        """
        return iter_avalon_projects(self._db_avalon)


def iter_avalon_projects(database):
    """Iter projects from Avalon MongoDB

    :param database: A Mongo database object
    :type database: MongoDatabase
    :return: Project item iterator
    :rtype: collections.Iterator[Project]
    """
    f = {"name": {"$regex": r"^(?!system\.)"}}  # non-system only
    db = database

    _projection = {
        "type": True,
        "name": True,
        "data": True,
    }

    for name in sorted(db.list_collection_names(filter=f)):

        query_filter = {"type": "project", "name": {"$exists": 1}}
        coll = db.get_collection(name)
        doc = coll.find_one(query_filter, projection=_projection)

        if doc is not None:
            is_active = bool(doc["data"].get("active", True))

            yield Project(
                name=name,
                is_active=is_active,
                coll=coll,
                _doc=doc,
            )


def iter_avalon_assets(avalon_project):
    """Iter assets in breadth first manner

    If `silo` exists, silos will be iterated first as Asset.

    :param avalon_project: A Project item that sourced from Avalon
    :type avalon_project: Project
    :return: Asset item iterator
    :rtype: collections.Iterator[Asset]
    """
    this = avalon_project

    _projection = {
        "name": True,
        "silo": True,
        "data.trash": True,
        "data.visualParent": True,
    }

    all_asset_docs = {d["_id"]: d for d in this.coll.find({
        "type": "asset",
        "name": {"$exists": 1},
    }, projection=_projection)}

    def count_depth(doc_):
        def depth(_d):
            p = _d["data"].get("visualParent")
            yield 0 if p is None else 1 + sum(depth(all_asset_docs[p]))
        return sum(depth(doc_))

    def group_key(doc_):
        """Key for sort/group assets by visual hierarchy depth
        :param dict doc_: Asset document
        :rtype: tuple[bool, ObjectId] or tuple[bool, str]
        """
        _depth = count_depth(doc_)
        _vp = doc_["data"]["visualParent"] if _depth else doc_["silo"]
        return _depth, _vp

    grouped_assets = [(k, list(group)) for k, group in groupby(
        sorted(all_asset_docs.values(), key=group_key),
        key=group_key
    )]

    _silos = dict()
    for (is_child, key), assets in grouped_assets:
        if not isinstance(key, str):
            continue
        silo = Asset(
            name=key,
            project=this,
            parent=None,
            is_silo=True,
            is_hidden=False,
            coll=this.coll,
            _doc=None,
        )
        _silos[key] = silo

        yield silo

    _assets = dict()
    for (is_child, key), assets in grouped_assets:
        for doc in assets:
            _parent = _assets[key] if is_child else _silos[key]
            _hidden = _parent.is_hidden or bool(doc["data"].get("trash"))
            asset = Asset(
                name=doc["name"],
                project=this,
                parent=_parent,
                is_silo=False,
                is_hidden=_hidden,
                coll=this.coll,
                _doc=doc,
            )
            _assets[doc["_id"]] = asset

            yield asset


if __name__ == "__main__":
    from Qt5 import QtGui, QtWidgets

    app = QtWidgets.QApplication()

    dialog = QtWidgets.QDialog()
    combo = QtWidgets.QComboBox()
    model = QtGui.QStandardItemModel()
    view = QtWidgets.QTreeView()
    view.setModel(model)

    # setup model

    avalon = AvalonMongo(uri=os.environ["AVALON_MONGO"])
    for project in avalon.iter_projects():
        combo.addItem(project.name, project)

    # signal

    def update_assets(index):
        project_item = combo.itemData(index)
        model.clear()
        _asset_items = dict()
        for asset in project_item.iter_assets():
            if asset.is_hidden:
                continue
            item = QtGui.QStandardItem(asset.name)
            _asset_items[asset.name] = item
            if asset.is_silo:
                model.appendRow(item)
            else:
                parent = _asset_items[asset.parent.name]
                parent.appendRow(item)

    combo.currentIndexChanged.connect(update_assets)

    # layout

    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(combo)
    layout.addWidget(view)

    # run

    dialog.open()
    app.exec_()
