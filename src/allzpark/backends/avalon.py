
import os
import time
import logging
import getpass
from itertools import groupby
from dataclasses import dataclass
from functools import singledispatch
from typing import Iterator, overload, List, Union, Set

from bson.objectid import ObjectId
from pymongo import MongoClient
from pymongo.database import Database as MongoDatabase
from pymongo.collection import Collection as MongoCollection

from ..core import SuiteTool, ReadOnlySuite


log = logging.getLogger(__name__)


def get_entrance(uri, timeout=1000):
    return Entrance(uri=uri, timeout=timeout)


SUITE_BRANCH = "avalon"
MEMBER_ROLE = "member"
MANAGER_ROLE = "admin"


class _Scope:

    @overload
    def iter_children(self: "Entrance") -> Iterator["Project"]:
        ...

    @overload
    def iter_children(self: "Project") -> Iterator["Asset"]:
        ...

    @overload
    def iter_children(self: "Asset") -> Iterator["Task"]:
        ...

    def iter_children(self):
        """Iter child scopes

        :type self: Entrance or Project or Asset
        :return:
        :rtype: Iterator[Project] or Iterator[Asset] or Iterator[Task]
        """
        return iter_avalon_scopes(self)

    @overload
    def list_tools(self: "Project", suite: ReadOnlySuite) -> List[SuiteTool]:
        ...

    @overload
    def list_tools(self: "Asset", suite: ReadOnlySuite) -> List[SuiteTool]:
        ...

    @overload
    def list_tools(self: "Task", suite: ReadOnlySuite) -> List[SuiteTool]:
        ...

    def list_tools(self, suite):
        """

        :param suite:
        :type suite: ReadOnlySuite
        :type self: Project or Asset or Task
        :return:
        :rtype: List[SuiteTool]
        """
        return list_role_filtered_tools(self, suite)

    @overload
    def obtain_workspace(self: "Project", tool: SuiteTool) -> Union[str, None]:
        ...

    @overload
    def obtain_workspace(self: "Asset", tool: SuiteTool) -> Union[str, None]:
        ...

    @overload
    def obtain_workspace(self: "Task", tool: SuiteTool) -> Union[str, None]:
        ...

    def obtain_workspace(self, tool):
        """

        :param tool:
        :type tool: SuiteTool
        :type self: Project or Asset or Task
        :return:
        :rtype: str or None
        """
        return obtain_avalon_workspace(self, tool)

    @overload
    def additional_env(self: "Project", tool: SuiteTool) -> dict:
        ...

    @overload
    def additional_env(self: "Asset", tool: SuiteTool) -> dict:
        ...

    @overload
    def additional_env(self: "Task", tool: SuiteTool) -> dict:
        ...

    def additional_env(self, tool):
        """

        :param tool:
        :type tool: SuiteTool
        :type self: Project or Asset or Task
        :return:
        :rtype: dict
        """
        return avalon_pipeline_env(self, tool)


@dataclass
class Entrance(_Scope):
    uri: str
    timeout: int


@dataclass
class Project(_Scope):
    name: str
    is_active: bool
    coll: MongoCollection
    roles: Set[str]
    root: str
    username: str
    _work_template: None

    @property
    def work_template(self):
        if self._work_template is None:
            _doc = self.coll.find_one(
                {"type": "project"}, projection={"config.template.work": True}
            )
            self._work_template = _doc["config"]["template"]["work"]
        return self._work_template


@dataclass
class Asset(_Scope):
    name: str
    project: Project
    parent: "Asset" or None
    silo: str
    is_silo: bool
    is_hidden: bool
    coll: MongoCollection


@dataclass
class Task(_Scope):
    name: str
    project: Project
    asset: Asset
    coll: MongoCollection


@singledispatch
def iter_avalon_scopes(scope):
    """Iter Avalon projects/assets/tasks

    :param scope: The scope of workspace. Could be a project/asset/task.
    :type scope: Entrance or Project or Asset
    :rtype: Iterator[Project] or Iterator[Asset] or Iterator[Task] or None
    """
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@iter_avalon_scopes.register
def _(scope: Entrance) -> Iterator[Project]:
    database = AvalonMongo(scope.uri, scope.timeout)
    return iter_avalon_projects(database)


@iter_avalon_scopes.register
def _(scope: Project) -> Iterator[Asset]:
    return iter_avalon_assets(scope)


@iter_avalon_scopes.register
def _(scope: Asset) -> Iterator[Task]:
    return iter_avalon_tasks(scope)


@iter_avalon_scopes.register
def _(scope: Task) -> None:
    raise StopIteration(f"Endpoint reached: {scope}")


@singledispatch
def list_role_filtered_tools(scope, suite):
    """

    :param scope: The scope of workspace. Could be a project/asset/task.
    :param suite: A loaded Rez suite.
    :type scope: Project or Asset or Task
    :type suite: ReadOnlySuite
    :return: A list of available tools in given scope
    :rtype: list[SuiteTool]
    """
    _ = suite  # consume unused arg
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@list_role_filtered_tools.register
def _(scope: Entrance, suite: ReadOnlySuite) -> None:
    _ = suite  # consume unused arg
    raise Exception(f"No tools are allowed in {type(scope)} scope.")


@list_role_filtered_tools.register
def _(scope: Project, suite: ReadOnlySuite) -> List[SuiteTool]:
    return [
        tool for tool in suite.iter_tools()
        if tool.ctx_name.startswith("project.")
        and (not tool.metadata.required_roles
             or scope.roles.intersection(tool.metadata.required_roles))
    ]


@list_role_filtered_tools.register
def _(scope: Asset, suite: ReadOnlySuite) -> List[SuiteTool]:
    return [
        tool for tool in suite.iter_tools()
        if tool.ctx_name.startswith("asset.")
        and (not tool.metadata.required_roles
             or scope.project.roles.intersection(tool.metadata.required_roles))
    ]


@list_role_filtered_tools.register
def _(scope: Task, suite: ReadOnlySuite) -> List[SuiteTool]:
    return [
        tool for tool in suite.iter_tools()
        if not tool.ctx_name.startswith("project.")
        and not tool.ctx_name.startswith("asset.")
        and (not tool.metadata.required_roles
             or scope.project.roles.intersection(tool.metadata.required_roles))
    ]


@singledispatch
def obtain_avalon_workspace(scope, tool):
    """

    :param scope: The scope of workspace. Could be at project/asset/task.
    :param tool: A tool provided by from Rez suite.
    :type scope: Project or Asset or Task
    :type tool:
    :return: A filesystem path to workspace if available
    :rtype: str or None
    """
    _ = tool  # consume unused arg
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@obtain_avalon_workspace.register
def _(scope: Entrance, tool: SuiteTool) -> None:
    log.error(f"No workspace for {tool.name} in scope {scope}.")
    raise Exception(f"No workspace for {type(scope)} scope.")


@obtain_avalon_workspace.register
def _(scope: Project, tool: SuiteTool) -> Union[str, None]:
    log.debug(f"No workspace for {tool.name} in scope {scope}.")
    return None


@obtain_avalon_workspace.register
def _(scope: Asset, tool: SuiteTool) -> Union[str, None]:
    log.debug(f"No workspace for {tool.name} in scope {scope}.")
    return None


@obtain_avalon_workspace.register
def _(scope: Task, tool: SuiteTool) -> Union[str, None]:
    return get_avalon_task_workspace(scope, tool)


@singledispatch
def avalon_pipeline_env(scope, tool):
    """

    :param scope: The scope of workspace. Could be at project/asset/task.
    :param tool: A tool provided by from Rez suite.
    :type scope: Project or Asset or Task
    :type tool:
    :return:
    :rtype: dict
    """
    _ = tool  # consume unused arg
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@avalon_pipeline_env.register
def _(scope: Entrance, tool: SuiteTool) -> None:
    _ = tool  # consume unused arg
    raise Exception(f"No environment for {type(scope)} scope.")


@avalon_pipeline_env.register
def _(scope: Project, tool: SuiteTool) -> dict:
    project = scope
    return {
        "AVALON_PROJECTS": project.root,
        "AVALON_PROJECT": project.name,
        "AVALON_APP": tool.name,
        "AVALON_APP_NAME": tool.name,  # application dir
    }


@avalon_pipeline_env.register
def _(scope: Asset, tool: SuiteTool) -> dict:
    asset = scope
    return {
        "AVALON_SILO": asset.silo,
        "AVALON_ASSET": asset.name,
        "AVALON_APP": tool.name,
        "AVALON_APP_NAME": tool.name,  # application dir
    }


@avalon_pipeline_env.register
def _(scope: Task, tool: SuiteTool) -> dict:
    task = scope
    return {
        "AVALON_TASK": task.name,
        "AVALON_WORKDIR": get_avalon_task_workspace(task, tool),
        "AVALON_APP": tool.name,
        "AVALON_APP_NAME": tool.name,  # application dir
    }


def get_avalon_task_workspace(task: Task, tool: SuiteTool):
    template = task.project.work_template
    return template.format(**{
        "root": task.project.root,
        "project": task.project.name,
        "silo": task.asset.silo,
        "asset": task.asset.name,
        "task": task.name,
        "app": tool.name,
        "user": task.project.username,
    })


def iter_avalon_projects(database):
    """Iter projects from Avalon MongoDB

    :param AvalonMongo database: An AvalonMongo connection instance
    :return: Project item iterator
    :rtype: Iterator[Project]
    """
    username = getpass.getuser()
    db_avalon = os.getenv("AVALON_DB", "avalon")
    db = database.conn[db_avalon]  # type: MongoDatabase
    f = {"name": {"$regex": r"^(?!system\.)"}}  # non-system only

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
            project_root = doc["data"]["root"]

            roles = set()
            _role_book = doc["data"].get("role", {})
            if username in _role_book.get(MEMBER_ROLE, []):
                roles.add(MEMBER_ROLE)
            if username in _role_book.get(MANAGER_ROLE, []):
                roles.add(MANAGER_ROLE)

            yield Project(
                name=name,
                is_active=is_active,
                coll=coll,
                roles=roles,
                root=project_root,
                username=username,
                _work_template=None,  # lazy loaded
            )


def iter_avalon_assets(avalon_project):
    """Iter assets in breadth first manner

    If `silo` exists, silos will be iterated first as Asset.

    :param avalon_project: A Project item that sourced from Avalon
    :type avalon_project: Project
    :return: Asset item iterator
    :rtype: Iterator[Asset]
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
            silo="",
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
                silo=doc.get("silo"),
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
    :rtype: Iterator[Task]
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
    from allzpark.core import get_avalon_entrance
    from Qt5 import QtGui, QtWidgets

    _entrance = get_avalon_entrance(uri=os.environ["AVALON_MONGO"])

    app = QtWidgets.QApplication()  # must be inited before all other widgets
    dialog = QtWidgets.QDialog()
    combo = QtWidgets.QComboBox()
    model = QtGui.QStandardItemModel()
    view = QtWidgets.QTreeView()
    view.setModel(model)

    # setup model
    for project_ in _entrance.iter_children():
        if project_.is_active:
            combo.addItem(project_.name, project_)

    # layout
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(combo)
    layout.addWidget(view)

    # signal
    def update_assets(index):
        project_item = combo.itemData(index)  # type: Project
        model.clear()
        _asset_items = dict()
        for asset in project_item.iter_children():
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
