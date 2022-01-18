
import os
import time
import logging
import getpass
from itertools import groupby
from dataclasses import dataclass
from bson.objectid import ObjectId
from pymongo import MongoClient
from pymongo.database import Database as MongoDatabase
from pymongo.collection import Collection as MongoCollection


log = logging.getLogger(__name__)


class Constants:
    SUITE_BRANCH = "avalon"
    PROJECT_MEMBER_ROLE = 1
    PROJECT_MANAGER_ROLE = 2


class AvalonMongo(object):
    """Avalon MongoDB connector
    """
    def __init__(self, uri, timeout=1000):
        """
        :param str uri: MongoDB URI string
        :param int timeout: MongoDB connection timeout, default 1000
        """
        conn = MongoClient(uri, serverSelectionTimeoutMS=timeout)

        self.uri = uri
        self.conn = conn
        self.timeout = timeout

    def iter_projects(self):
        """Iter projects

        :return: Project item iterator
        :rtype: collections.Iterator[Project]
        """
        return iter_avalon_projects(self)


class AvalonScope:

    def list_tools(self, suite):
        """
        :param suite:
        :type suite:
        :type self: Project or Asset or Task
        :return:
        """
        return list_role_filtered_tools(self, suite)

    def obtain_workspace(self, tool):
        """
        :param tool:
        :type tool:
        :type self: Project or Asset or Task
        :return:
        """
        return obtain_avalon_workspace(self, tool)

    def additional_env(self, tool):
        """
        :param tool:
        :type tool:
        :type self: Project or Asset or Task
        :return:
        """
        return avalon_pipeline_env(self, tool)


@dataclass
class Project(AvalonScope):
    name: str
    is_active: bool
    coll: MongoCollection
    role: int

    def iter_assets(self):
        """Iter assets in breadth first manner

        If `silo` exists, silos will be iterated first as Asset.

        :return: Asset item iterator
        :rtype: collections.Iterator[Asset]
        """
        return iter_avalon_assets(self)


@dataclass
class Asset(AvalonScope):
    name: str
    project: Project
    parent: "Asset" or None
    is_silo: bool
    is_hidden: bool
    coll: MongoCollection

    def iter_tasks(self):
        """Iter tasks in specific asset

        :return: Task item iterator
        :rtype: collections.Iterator[Task]
        """
        return iter_avalon_tasks(self)


@dataclass
class Task(AvalonScope):
    name: str
    project: Project
    asset: Asset
    coll: MongoCollection


def iter_avalon_projects(database):
    """Iter projects from Avalon MongoDB

    :param AvalonMongo database: An AvalonMongo connection instance
    :return: Project item iterator
    :rtype: collections.Iterator[Project]
    """
    db_avalon = os.getenv("AVALON_DB", "avalon")
    db = database.conn[db_avalon]  # type: MongoDatabase
    f = {"name": {"$regex": r"^(?!system\.)"}}  # non-system only

    _username = getpass.getuser()
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

            _role_book = doc["data"].get("role", {})
            _is_member = _username in _role_book.get("member", [])
            _is_admin = _username in _role_book.get("admin", [])
            role = (
                (Constants.PROJECT_MEMBER_ROLE if _is_member else 0)
                | (Constants.PROJECT_MANAGER_ROLE if _is_admin else 0)
            )

            yield Project(
                name=name,
                is_active=is_active,
                coll=coll,
                role=role,
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
            )
            _assets[doc["_id"]] = asset

            yield asset


def iter_avalon_tasks(avalon_asset):
    """Iter tasks in specific asset

    :param avalon_asset: A Asset item that sourced from Avalon
    :type avalon_asset: Asset
    :return: Task item iterator
    :rtype: collections.Iterator[Task]
    """
    this = avalon_asset

    query_filter = {"type": "asset", "name": this.name}
    doc = this.coll.find_one(query_filter, projection={"tasks": True})
    if doc is not None:
        for task in doc.get("tasks"):
            yield Task(
                name=task,
                project=this.project,
                asset=this,
                coll=this.coll,
            )


def list_role_filtered_tools(scope, suite):
    """

    :param scope: The scope of workspace. Could be a project/asset/task.
    :param suite: A loaded Rez suite.
    :type scope: Project or Asset or Task
    :return: A list of available tools in given scope
    :rtype: list[]
    """


def obtain_avalon_workspace(scope, tool):
    """

    :param scope: The scope of workspace. Could be at project/asset/task.
    :param tool: A tool provided by from Rez suite.
    :type scope: Project or Asset or Task
    :type tool:
    :return: A filesystem path to workspace if available
    :rtype: str or None
    """


def avalon_pipeline_env(scope, tool):
    """

    :param scope: The scope of workspace. Could be at project/asset/task.
    :param tool: A tool provided by from Rez suite.
    :type scope: Project or Asset or Task
    :type tool:
    :return:
    :rtype: dict
    """


def ping(database, retry=3):
    """Test database connection with retry

    :param AvalonMongo database: An AvalonMongo connection instance
    :param int retry: Max retry times, default 3
    :return: None
    :raises IOError: If not able to connect in given retry times
    """
    for i in range(retry):
        try:
            t1 = time.time()
            database.conn.server_info()

        except Exception:
            log.error(f"Retrying..[{i}]")
            time.sleep(1)
            database.timeout *= 1.5

        else:
            break

    else:
        raise IOError(
            "ERROR: Couldn't connect to %s in less than %.3f ms"
            % (database.uri, database.timeout)
        )

    log.info(
        "Connected to %s, delay %.3f s" % (database.uri, time.time() - t1)
    )


if __name__ == "__main__":
    from Qt5 import QtGui, QtWidgets

    app = QtWidgets.QApplication()  # must be inited before all other widgets
    dialog = QtWidgets.QDialog()
    combo = QtWidgets.QComboBox()
    model = QtGui.QStandardItemModel()
    view = QtWidgets.QTreeView()
    view.setModel(model)

    # setup model
    avalon = AvalonMongo(uri=os.environ["AVALON_MONGO"])
    for project in avalon.iter_projects():
        if project.is_active:
            combo.addItem(project.name, project)

    # layout
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(combo)
    layout.addWidget(view)

    # signal
    def update_assets(index):
        project_item = combo.itemData(index)
        model.clear()
        _asset_items = dict()
        for asset in project_item.iter_assets():
            if not asset.is_hidden:
                item = QtGui.QStandardItem(asset.name)
                _asset_items[asset.name] = item
                if asset.is_silo:
                    model.appendRow(item)
                else:
                    parent = _asset_items[asset.parent.name]
                    parent.appendRow(item)

    combo.currentIndexChanged.connect(update_assets)

    # run
    dialog.open()
    app.exec_()
