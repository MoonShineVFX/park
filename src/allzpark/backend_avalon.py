
import os
import time
import logging
import getpass
from itertools import groupby
from dataclasses import dataclass
from functools import singledispatch
from typing import \
    Iterator, overload, Union, Set, Callable, TYPE_CHECKING
from bson.objectid import ObjectId
from pymongo import MongoClient
from pymongo.database import Database as MongoDatabase
from pymongo.collection import Collection as MongoCollection
from rez.config import config as rezconfig

from .exceptions import BackendError
from .util import elide


if TYPE_CHECKING:
    # avoid cyclic import
    from .core import SuiteTool
else:
    SuiteTool = "SuiteTool"
    # related references:
    #   https://stackoverflow.com/a/61544901
    #   https://stackoverflow.com/a/39205612
ToolFilterCallable = Callable[[SuiteTool], bool]


log = logging.getLogger(__name__)


parkconfig = rezconfig.plugins.command.park


def get_entrance(uri=None, timeout=None):
    """

    :param str uri:
    :param int timeout:
    :return:
    :rtype: Entrance
    """
    out = timeout or int(os.getenv("AVALON_TIMEOUT") or 1000)
    uri = uri or os.getenv("AVALON_MONGO")
    if uri:
        return Entrance(uri=uri, timeout=out)
    raise BackendError("Avalon database URI not given.")


MEMBER_ROLE = "member"
MANAGER_ROLE = "admin"


class _Scope:

    def exists(
            self: Union["Entrance", "Project", "Asset", "Task"]
    ) -> bool:
        # todo: this should query database to see if the entity that
        #  this scope represented still exists.
        pass

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
    def suite_path(self: "Entrance") -> Union[str, None]:
        ...

    @overload
    def suite_path(self: "Project") -> str:
        ...

    @overload
    def suite_path(self: Union["Asset", "Task"]) -> None:
        ...

    def suite_path(self):
        """Iter child scopes

        :type self: Entrance or Project or Asset or Task
        :return:
        :rtype: Union[str, None]
        """
        return scope_suite_path(self)

    def make_tool_filter(
            self: Union["Entrance", "Project", "Asset", "Task"]
    ) -> ToolFilterCallable:
        """
        :return:
        """
        return tool_filter_factory(self)

    def obtain_workspace(
            self: Union["Entrance", "Project", "Asset", "Task"],
            tool: SuiteTool
    ) -> Union[str, None]:
        """

        :param tool:
        :type tool: SuiteTool
        :type self: Entrance or Project or Asset or Task
        :return:
        :rtype: str or None
        """
        return obtain_avalon_workspace(self, tool)

    def additional_env(
            self: Union["Entrance", "Project", "Asset", "Task"],
            tool: SuiteTool
    ) -> dict:
        """

        :param tool:
        :type tool: SuiteTool
        :type self: Entrance or Project or Asset or Task
        :return:
        :rtype: dict
        """
        return avalon_pipeline_env(self, tool)


@dataclass(frozen=True)
class Entrance(_Scope):
    name = "avalon"
    upstream = None
    uri: str
    timeout: int


@dataclass(frozen=True)
class Project(_Scope):
    name: str
    upstream: Entrance
    is_active: bool
    roles: Set[str]
    tasks: Set[str]
    root: str
    username: str
    work_template: str
    coll: MongoCollection


@dataclass(frozen=True)
class Asset(_Scope):
    name: str
    upstream: Project or "Asset"
    project: Project
    parent: "Asset" or None
    silo: str
    tasks: Set[str]
    is_silo: bool
    is_hidden: bool
    coll: MongoCollection


@dataclass(frozen=True)
class Task(_Scope):
    name: str
    upstream: Asset
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
    database = AvalonMongo(scope.uri, scope.timeout, entrance=scope)
    return iter_avalon_projects(database)


@iter_avalon_scopes.register
def _(scope: Project) -> Iterator[Asset]:
    return iter_avalon_assets(scope)


@iter_avalon_scopes.register
def _(scope: Asset) -> Iterator[Task]:
    return iter_avalon_tasks(scope)


@iter_avalon_scopes.register
def _(scope: Task) -> tuple:
    log.debug(f"Endpoint reached: {elide(scope)}")
    return ()


@singledispatch
def tool_filter_factory(scope) -> ToolFilterCallable:
    """

    :param scope: The scope of workspace. Could be a project/asset/task.
    :type scope: Entrance or Project or Asset or Task
    :return: A callable filter function
    """
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@tool_filter_factory.register
def _(scope: Entrance) -> ToolFilterCallable:
    def _filter(tool: SuiteTool) -> bool:
        required_roles = tool.metadata.required_roles
        return (
            not tool.metadata.hidden
            and (not required_roles
                 or getpass.getuser() in required_roles)
        )
    _ = scope  # consume unused arg
    return _filter


@tool_filter_factory.register
def _(scope: Project) -> ToolFilterCallable:
    def _filter(tool: SuiteTool) -> bool:
        required_roles = tool.metadata.required_roles
        return (
            not tool.metadata.hidden
            and tool.ctx_name.startswith("project.")
            and (not required_roles
                 or scope.roles.intersection(required_roles))
        )
    return _filter


@tool_filter_factory.register
def _(scope: Asset) -> ToolFilterCallable:
    def _filter(tool: SuiteTool) -> bool:
        required_roles = tool.metadata.required_roles
        return (
            not tool.metadata.hidden
            and tool.ctx_name.startswith("asset.")
            and (not required_roles
                 or scope.project.roles.intersection(required_roles))
        )
    return _filter


@tool_filter_factory.register
def _(scope: Task) -> ToolFilterCallable:
    def _filter(tool: SuiteTool) -> bool:
        required_roles = tool.metadata.required_roles
        return (
            not tool.metadata.hidden
            and not tool.ctx_name.startswith("project.")
            and not tool.ctx_name.startswith("asset.")
            and (not required_roles
                 or scope.project.roles.intersection(required_roles))
        )
    return _filter


@singledispatch
def obtain_avalon_workspace(scope, tool):
    """

    :param scope: The scope of workspace. Could be at project/asset/task.
    :param tool: A tool provided by Rez suite.
    :type scope: Entrance or Project or Asset or Task
    :type tool: SuiteTool
    :return: A filesystem path to workspace if available
    :rtype: str or None
    """
    _ = tool  # consume unused arg
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@obtain_avalon_workspace.register
def _(scope: Entrance, tool: SuiteTool) -> None:
    log.debug(f"No workspace for {tool.name} in Avalon scope {elide(scope)}.")
    return None


@obtain_avalon_workspace.register
def _(scope: Project, tool: SuiteTool) -> Union[str, None]:
    log.debug(f"No workspace for {tool.name} in Avalon scope {elide(scope)}.")
    return None


@obtain_avalon_workspace.register
def _(scope: Asset, tool: SuiteTool) -> Union[str, None]:
    log.debug(f"No workspace for {tool.name} in Avalon scope {elide(scope)}.")
    return None


@obtain_avalon_workspace.register
def _(scope: Task, tool: SuiteTool) -> Union[str, None]:
    return get_avalon_task_workspace(scope, tool)


@singledispatch
def avalon_pipeline_env(scope, tool):
    """

    :param scope: The scope of workspace. Could be at project/asset/task.
    :param tool: A tool provided by from Rez suite.
    :type scope: Entrance or Project or Asset or Task
    :type tool: SuiteTool
    :return:
    :rtype: dict
    """
    _ = tool  # consume unused arg
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@avalon_pipeline_env.register
def _(scope: Entrance, tool: SuiteTool) -> dict:
    _ = scope, tool  # consume unused arg
    return {}


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


@singledispatch
def scope_suite_path(scope):
    """

    :param scope: The scope of workspace. Could be at project/asset/task.
    :type scope: Entrance or Project or Asset or Task
    :return: A filesystem path to workspace if available
    :rtype: str or None
    """
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@scope_suite_path.register
def _(scope: Entrance) -> Union[str, None]:
    _ = scope
    return os.getenv("AVALON_DEFAULT_SUITE")


@scope_suite_path.register
def _(scope: Project) -> str:
    roots = parkconfig.suite_roots()
    if not isinstance(roots, dict):
        raise BackendError("Invalid configuration, 'suite_roots' should be "
                           "dict type value.")

    avalon_suite_root = roots.get("avalon")
    if not avalon_suite_root:
        raise BackendError("Invalid configuration, no suite root for Avalon")

    return os.path.join(avalon_suite_root, scope.name)


@scope_suite_path.register
def _(scope: Asset) -> None:
    _ = scope
    return None


@scope_suite_path.register
def _(scope: Task) -> None:
    _ = scope
    return None


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
        "config.tasks.name": True,
        "config.template.work": True,
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

            tasks = set()
            for task in doc["config"]["tasks"]:
                tasks.add(task["name"])

            yield Project(
                name=name,
                upstream=database.entrance,
                is_active=is_active,
                roles=roles,
                tasks=tasks,
                root=project_root,
                username=username,
                work_template=doc["config"]["template"]["work"],
                coll=coll,
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
        "data.tasks": True,
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
        :rtype: tuple[int, ObjectId] or tuple[int, str] or tuple[int, None]
        """
        _depth = count_depth(doc_)
        _vp = doc_["data"]["visualParent"] if _depth else doc_.get("silo")
        return _depth, _vp

    grouped_assets = [
        ((depth, key), list(group)) for (depth, key), group in
        groupby(sorted(all_asset_docs.values(), key=group_key), key=group_key)
    ]

    _silos = dict()
    for (depth, key), assets in grouped_assets:
        if not isinstance(key, str):
            continue  #

        silo = Asset(
            name=key,
            upstream=this,
            project=this,
            parent=None,
            silo="",
            tasks=set(),
            is_silo=True,
            is_hidden=False,
            coll=this.coll,
        )
        _silos[key] = silo

        yield silo

    _assets = dict()
    for (depth, key), assets in grouped_assets:
        for doc in assets:
            _parent = _assets[key] if depth else _silos.get(key)
            _hidden = _parent.is_hidden or bool(doc["data"].get("trash"))
            asset = Asset(
                name=doc["name"],
                upstream=_parent or this,
                project=this,
                parent=_parent,
                silo=doc.get("silo"),
                tasks=set(doc["data"].get("tasks") or []),
                is_silo=False,
                is_hidden=_hidden,
                coll=this.coll,
            )
            _assets[doc["_id"]] = asset

            yield asset


def iter_avalon_tasks(avalon_asset):
    """Iter tasks in specific asset

    If asset doesn't have any task assigned, all tasks defined in project
    will be given.

    :param avalon_asset: A Asset item that sourced from Avalon
    :type avalon_asset: Asset
    :return: Task item iterator
    :rtype: Iterator[Task]
    """
    this = avalon_asset
    for task in this.tasks or this.project.tasks:
        yield Task(
            name=task,
            upstream=this,
            project=this.project,
            asset=this,
            coll=this.coll,
        )


class AvalonMongo(object):
    """Avalon MongoDB connector
    """
    def __init__(self, uri, timeout=1000, entrance=None):
        """
        :param str uri: MongoDB URI string
        :param int timeout: MongoDB connection timeout, default 1000
        :param entrance: The entrance scope that used to open this
            connection. Optional.
        :type entrance: Entrance or None
        """
        conn = MongoClient(uri, serverSelectionTimeoutMS=timeout)

        self.uri = uri
        self.conn = conn
        self.timeout = timeout
        self.entrance = entrance


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
