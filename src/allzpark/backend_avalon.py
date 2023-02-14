
import os
import time
import logging
import getpass
import functools
from itertools import groupby
from dataclasses import dataclass
from functools import singledispatch
from collections import MutableMapping
from typing import Iterator, overload, Union, Set, List, Callable
from bson.objectid import ObjectId
from pymongo import MongoClient
from pymongo.database import Database as MongoDatabase
from pymongo.collection import Collection as MongoCollection
from pymongo.results import UpdateResult
from rez.config import config as rezconfig

from .exceptions import BackendError
from .util import elide
from .core import SuiteTool, AbstractScope
# Note:
#   In case the cyclic import between this module and `.core` pops out
#   again in future change, here's some related references:
#   https://stackoverflow.com/a/61544901
#   https://stackoverflow.com/a/39205612

# typing
ToolFilterCallable = Callable[[SuiteTool], bool]


log = logging.getLogger("allzpark")


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
        return Entrance(uri=uri, timeout=out, joined=True)
    raise BackendError("Avalon database URI not given.")


MEMBER_ROLE = "member"
MANAGER_ROLE = "admin"
DEVELOPER_ROLE = "developer"


class _Scope(AbstractScope):

    def exists(
            self: Union["Entrance", "Project", "Asset", "Task"]
    ) -> bool:
        return check_existence(self)

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
            tool: SuiteTool = None,
    ) -> str:
        """

        :param tool:
        :type tool: SuiteTool or None
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

    def current_user_roles(
            self: Union["Entrance", "Project", "Asset", "Task"]
    ) -> list:
        """
        :type self: Entrance or Project or Asset or Task
        :return:
        :rtype: list
        """
        return avalon_current_user_roles(self)

    def generate_breadcrumb(
            self: Union["Entrance", "Project", "Asset", "Task"]
    ) -> dict:
        """
        :type self: Entrance or Project or Asset or Task
        :return:
        :rtype: dict
        """
        return generate_avalon_scope_breadcrumb(self)


@dataclass  # can't froze this, attribute 'joined' can be changed
class Entrance(_Scope):
    name = "avalon"
    upstream = None
    uri: str
    timeout: int
    joined: bool

    def __repr__(self):
        return f"Entrance(" \
               f"name={self.name}, uri={self.uri}, joined={self.joined})"

    def __hash__(self):
        return hash(repr(self))

    def get_scope_from_breadcrumb(self, breadcrumb: dict):
        return get_scope_from_breadcrumb(self, breadcrumb)


@dataclass
class Project(_Scope):
    name: str
    upstream: Entrance
    is_active: bool
    roles: Set[str]
    tasks: List[str]
    root: str
    username: str
    work_template: str
    coll: str
    db: "AvalonMongo"
    cacheRoot: str

    def __repr__(self):
        return f"Project(name={self.name}, upstream={self.upstream})"

    def __hash__(self):
        return hash(repr(self))


@dataclass
class Asset(_Scope):
    name: str
    label: str
    upstream: Project
    project: Project
    parent: "Asset" or None
    silo: str
    episode: str
    sequence: str
    asset_type: str
    tasks: List[str]
    is_silo: bool
    is_episode: bool
    is_sequence: bool
    is_asset_type: bool
    is_leaf: bool
    is_hidden: bool
    child_task: set
    coll: str
    db: "AvalonMongo"

    def __repr__(self):
        return f"Asset(name={self.name}, label={self.label}, " \
               f"upstream={self.upstream})"

    def __hash__(self):
        return hash(repr(self))


@dataclass
class Task(_Scope):
    name: str
    upstream: Asset
    project: Project
    asset: Asset
    coll: str
    db: "AvalonMongo"

    def __repr__(self):
        return f"Task(name={self.name}, upstream={self.upstream})"

    def __hash__(self):
        return hash(repr(self))


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
    return iter_avalon_projects(database, scope.joined)


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
        ctx_category = tool.ctx_name.split(".", 1)[0]
        categories = {"entrance"}
        return (
            not tool.metadata.hidden
            and ctx_category in categories
            and (not required_roles
                 or getpass.getuser() in required_roles)
        )
    _ = scope  # consume unused arg
    return _filter


@tool_filter_factory.register
def _(scope: Project) -> ToolFilterCallable:
    def _filter(tool: SuiteTool) -> bool:
        required_roles = tool.metadata.required_roles
        ctx_category = tool.ctx_name.split(".", 1)[0]
        categories = {"project", "entrance"}
        return (
            not tool.metadata.hidden
            and ctx_category in categories
            and (not required_roles
                 or scope.roles.intersection(required_roles))
        )
    return _filter


@tool_filter_factory.register
def _(scope: Asset) -> ToolFilterCallable:
    def _filter(tool: SuiteTool) -> bool:
        required_roles = tool.metadata.required_roles
        ctx_category = tool.ctx_name.split(".", 1)[0]
        categories = {"asset", "project", "entrance"}
        return (
            not tool.metadata.hidden
            and ctx_category in categories
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
            and (not required_roles
                 or scope.project.roles.intersection(required_roles))
        )
    return _filter


@singledispatch
def obtain_avalon_workspace(scope, tool=None):
    """

    :param scope: The scope of workspace. Could be at project/asset/task.
    :param tool: A tool provided by Rez suite.
    :type scope: Entrance or Project or Asset or Task
    :type tool: SuiteTool or None
    :return: A filesystem path to workspace if available
    :rtype: str or None
    """
    _ = tool  # consume unused arg
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@obtain_avalon_workspace.register
def _(scope: Entrance, tool: SuiteTool = None) -> str:
    _ = scope, tool
    return os.getcwd()


@obtain_avalon_workspace.register
def _(scope: Project, tool: SuiteTool = None) -> str:
    _ = tool
    template = "{root}/{project}/Avalon"
    path = template.format(**{
        "root": scope.root,
        "project": scope.name,
    })
    return os.path.normpath(path).replace('\\', '/')


@obtain_avalon_workspace.register
def _(scope: Asset, tool: SuiteTool = None) -> str:
    _ = tool
    template = "{root}/{project}/Avalon"
    path = template.format(**{
        "root": scope.project.root,
        "project": scope.project.name,
    })
    return os.path.normpath(path).replace('\\', '/')


@obtain_avalon_workspace.register
def _(scope: Task, tool: SuiteTool = None) -> str:
    task = scope
    template = task.project.work_template
    if tool is None:
        template = template.split("{app}")[0]

    if task.asset.silo == "Assets":
        template = template.replace("{category}", "{asset_type}")
    elif task.asset.silo == "Shots":
        template = template.replace("{category}", "{episode}/{sequence}")
    else:
        template = template.replace("{category}", "")

    path = template.format(**{
        "root": task.project.root,
        "project": task.project.name,
        "silo": task.asset.silo,
        "episode": task.asset.episode,
        "sequence": task.asset.sequence,
        "asset_type": task.asset.asset_type,
        "asset": task.asset.name,
        "task": task.name,
        "app": tool.name if tool else "",
        "user": task.project.username,
    })
    return os.path.normpath(path).replace('\\', '/')


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
    environ = scope.upstream.additional_env(tool)
    environ.update({
        "AVALON_PROJECTS": project.root,
        "AVALON_PROJECT": project.name,
        "AVALON_APP": tool.name,
        "AVALON_APP_NAME": tool.name,  # application dir
        "AVALON_CACHE_ROOT": project.cacheRoot
    })
    return environ


@avalon_pipeline_env.register
def _(scope: Asset, tool: SuiteTool) -> dict:
    asset = scope
    environ = scope.upstream.additional_env(tool)
    environ.update({
        "AVALON_SILO": asset.silo,
        "AVALON_EPISODE": asset.episode,
        "AVALON_SEQUENCE": asset.sequence,
        "AVALON_ASSET_TYPE": asset.asset_type,
        "AVALON_ASSET": asset.name,
        "AVALON_APP": tool.name,
        "AVALON_APP_NAME": tool.name,  # application dir
    })
    return environ


@avalon_pipeline_env.register
def _(scope: Task, tool: SuiteTool) -> dict:
    task = scope
    environ = scope.upstream.additional_env(tool)
    environ.update({
        "AVALON_TASK": task.name,
        "AVALON_WORKDIR": obtain_avalon_workspace(task, tool),
        "AVALON_APP": tool.name,
        "AVALON_APP_NAME": tool.name,  # application dir
        "REZ_ALIAS_NAME": tool.alias
    })
    return environ

@singledispatch
def avalon_current_user_roles(scope):
    """

    :param scope: The scope of workspace. Could be at project/asset/task.
    :type scope: Entrance or Project or Asset or Task
    :return:
    :rtype: list
    """
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@avalon_current_user_roles.register
def _(scope: Entrance) -> list:
    _ = scope
    return []


@avalon_current_user_roles.register
def _(scope: Project) -> list:
    return scope.roles


@avalon_current_user_roles.register
def _(scope: Asset) -> list:
    return scope.upstream.current_user_roles()


@avalon_current_user_roles.register
def _(scope: Task) -> list:
    return scope.upstream.current_user_roles()


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
    return os.getenv("AVALON_ENTRANCE_SUITE")


@scope_suite_path.register
def _(scope: Project) -> str:
    roots = parkconfig.suite_roots  # type: dict
    if not isinstance(roots, MutableMapping):
        raise BackendError("Invalid configuration, 'suite_roots' should be "
                           f"dict-like type value, not {type(roots)}.")

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


@singledispatch
def check_existence(scope) -> bool:
    """Check if the scope still valid in Avalon database

    :param scope: The scope of workspace. Could be a project/asset/task.
    :type scope: Entrance or Project or Asset
    :rtype: Iterator[Project] or Iterator[Asset] or Iterator[Task] or None
    """
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@check_existence.register
def _(scope: Entrance) -> bool:
    try:
        ping(AvalonMongo(scope.uri, scope.timeout, entrance=scope))
    except IOError as e:
        log.critical(f"Avalon Database connection lost: {str(e)}")
        return False
    return True


@check_existence.register
def _(scope: Project) -> bool:
    return scope.db.is_project_exists(scope.coll)


@check_existence.register
def _(scope: Asset) -> bool:
    return scope.db.is_asset_exists(scope.coll, scope.name)


@check_existence.register
def _(scope: Task) -> bool:
    _ = scope
    return True


@singledispatch
def generate_avalon_scope_breadcrumb(scope):
    """

    :param scope: The scope of workspace. Could be at project/asset/task.
    :type scope: Entrance or Project or Asset or Task
    :return:
    :rtype: dict
    """
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@generate_avalon_scope_breadcrumb.register
def _(scope: Entrance) -> dict:
    return {"entrance": scope.name}


@generate_avalon_scope_breadcrumb.register
def _(scope: Project) -> dict:
    breadcrumb = scope.upstream.generate_breadcrumb()
    breadcrumb.update({"project": scope.coll})
    return breadcrumb


@generate_avalon_scope_breadcrumb.register
def _(scope: Asset) -> dict:
    breadcrumb = scope.upstream.generate_breadcrumb()
    breadcrumb.update({"asset": scope.name})
    return breadcrumb


@generate_avalon_scope_breadcrumb.register
def _(scope: Task) -> dict:
    breadcrumb = scope.upstream.generate_breadcrumb()
    breadcrumb.update({"task": scope.name})
    return breadcrumb


def get_scope_from_breadcrumb(entrance: Entrance, breadcrumb: dict):

    if "project" in breadcrumb:
        coll_name = breadcrumb["project"]
        db = AvalonMongo(entrance.uri, entrance.timeout, entrance=entrance)
        doc = db.find_project(coll_name)
        if doc:
            log.debug(f"Found avalon project: {coll_name}")
            project = _mk_project_scope(coll_name, doc, db)
        else:
            log.debug(f"Avalon project (collection) not found: {coll_name}")
            return
    else:
        return entrance

    if "asset" in breadcrumb:
        asset_name = breadcrumb["asset"]
        asset = next(
            # so to get a full asset hierarchy, and it's hidden state
            (a for a in project.iter_children() if a.name == asset_name), None
        )
        if asset is None:
            log.debug(f"Avalon asset not found: {asset_name}")
            return
        elif asset.is_hidden:
            log.debug(f"Avalon asset is now hidden: {asset_name}")
            return
        log.debug(f"Found avalon asset: {asset_name}")
    else:
        return project

    if "task" in breadcrumb:
        task_name = breadcrumb["task"]
        if task_name in asset.tasks:
            task = Task(
                name=task_name,
                upstream=asset,
                project=asset.project,
                asset=asset,
                coll=asset.coll,
                db=asset.db,
            )
            log.debug(f"Matched task {task_name!r} in asset {asset_name!r}")
            return task
        else:
            log.debug(f"Task {task_name!r} not assigned to asset {asset_name!r}")
            return
    else:
        return asset


def _mk_project_scope(coll_name, doc, database, active_only=True):
    is_active = bool(doc["data"].get("active", True))
    if active_only and not is_active:
        return

    username = getpass.getuser()
    project_root = doc["data"]["root"]

    roles = set()
    _role_book = doc["data"].get("role", {})
    if username in _role_book.get(MEMBER_ROLE, []):
        roles.add(MEMBER_ROLE)
    if username in _role_book.get(MANAGER_ROLE, []):
        roles.add(MANAGER_ROLE)
    if username in _role_book.get(DEVELOPER_ROLE, []):
        roles.add(DEVELOPER_ROLE)

    tasks = []
    for task in doc["config"]["tasks"]:
        if task["name"] not in tasks:
            tasks.append(task["name"])
    tasks.sort()

    cache_root = doc["data"].get("cacheRoot", project_root)

    # Check project created time, temp code for switch L: to Q:
    _p_time = doc["name"].split('_')[0]
    if _p_time.isdigit():
        if int(_p_time) <= 202208 and cache_root != "Q:":
            cache_root = "L:"

    return Project(
        name=doc["name"],
        upstream=database.entrance,
        is_active=is_active,
        roles=roles,
        tasks=tasks,
        root=project_root,
        username=username,
        work_template=doc["config"]["template"]["work"],
        coll=coll_name,
        db=database,
        cacheRoot=cache_root
    )


def iter_avalon_projects(database, joined=True, active_only=True):
    """Iter projects from Avalon MongoDB

    :param AvalonMongo database: An AvalonMongo connection instance
    :param bool joined:
    :param bool active_only:
    :return: Project item iterator
    :rtype: Iterator[Project]
    """
    for coll_name, doc in database.iter_projects(joined):
        scope = _mk_project_scope(coll_name, doc, database, active_only)
        if scope is not None:
            yield scope


def iter_avalon_assets(avalon_project):
    """Iter assets in breadth first manner

    If `silo` exists, silos will be iterated first as Asset.

    :param avalon_project: A Project item that sourced from Avalon
    :type avalon_project: Project
    :return: Asset item iterator
    :rtype: Iterator[Asset]
    """
    this = avalon_project
    grouped_assets = this.db.list_assets(this.coll)

    _silos = dict()
    for depth, key, assets in grouped_assets:
        if not isinstance(key, str):
            continue  #
        _hidden = this.db.get_silo_hidden(this.coll, key)
        silo = Asset(
            name=key,
            label=key,
            upstream=this,
            project=this,
            parent=None,
            silo="",
            episode="",
            sequence="",
            asset_type="",
            tasks=[],
            is_silo=True,
            is_episode=False,
            is_sequence=False,
            is_asset_type=False,
            is_hidden=_hidden,
            is_leaf=False,
            child_task=set(),
            coll=this.coll,
            db=this.db,
        )
        _silos[key] = silo

        yield silo

    _assets = dict()
    for depth, key, assets in grouped_assets:
        for doc in assets:
            _parent = _assets[key] if depth else _silos[key]
            _hidden = _parent.is_hidden or bool(doc["data"].get("trash"))
            _is_episode = doc["type"] == "episode"
            _episode = doc["name"] if _is_episode else _parent.episode
            _is_sequence = doc["type"] == "sequence"
            _sequence = doc["name"] if _is_sequence else _parent.sequence
            _is_asset_type = doc["type"] == "asset_type"
            _asset_type = doc["name"] if _is_asset_type else _parent.asset_type
            tasks = doc["data"].get("tasks") or []
            asset = Asset(
                name=doc["name"],
                label=doc["data"]['label'],
                upstream=this,
                project=this,
                parent=_parent,
                silo=doc.get("silo"),
                episode=_episode,
                sequence=_sequence,
                asset_type=_asset_type,
                tasks=tasks,
                is_silo=False,
                is_episode=_is_episode,
                is_sequence=_is_sequence,
                is_asset_type=_is_asset_type,
                is_leaf=True,
                is_hidden=_hidden,
                child_task=set(),
                coll=this.coll,
                db=this.db,
            )
            _parent.is_leaf = False
            _parent.child_task.update(tasks)
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
            db=this.db,
        )


@functools.lru_cache(maxsize=None)
def _get_connection(uri, timeout):
    return MongoClient(uri, serverSelectionTimeoutMS=timeout)


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
        conn = _get_connection(uri, timeout)

        self.uri = uri
        self.conn = conn
        self.timeout = timeout
        self.entrance = entrance
        self._db_name = os.getenv("AVALON_DB", "avalon")

    def is_project_exists(self, coll_name):
        db = self.conn[self._db_name]  # type: MongoDatabase
        coll = db.get_collection(coll_name)  # type: MongoCollection
        return bool(
            coll.find_one({"type": "project"},
                          projection={"_id": True})
        )

    def is_asset_exists(self, coll_name, asset_name):
        db = self.conn[self._db_name]  # type: MongoDatabase
        coll = db.get_collection(coll_name)  # type: MongoCollection
        return bool(
            coll.find_one({"type": "asset", "name": asset_name},
                          projection={"_id": True})
        )

    def find_project(self, coll_name, joined=True):
        _user = getpass.getuser()
        db = self.conn[self._db_name]  # type: MongoDatabase

        _projection = {
            "type": True,
            "name": True,
            "data": True,
            "config.tasks.name": True,
            "config.template.work": True,
        }
        query_filter = {
            "type": "project",
            "name": {"$exists": 1},
        }
        if joined is not None:
            query_filter.update({
                f"data.role.{MEMBER_ROLE}": _user if joined else {"$ne": _user}
            })
        coll = db.get_collection(coll_name)  # type: MongoCollection
        return coll.find_one(query_filter, projection=_projection)

    def iter_projects(self, joined=True):
        """
        :return: yielding tuples of mongodb collection name and project doc
        :rtype: tuple[str, dict]
        """
        db = self.conn[self._db_name]  # type: MongoDatabase
        f = {"name": {"$regex": r"^(?!system\.)"}}  # non-system only

        for name in sorted(db.list_collection_names(filter=f)):
            doc = self.find_project(name, joined)
            if doc:
                yield name, doc

    def list_assets(self, coll_name):  # todo: lur cache this
        """Listing assets in breadth first manner

        This returns a depth sorted list of tuple that holds grouped assets:
            1. depth-level (int)
            2. asset's visual parent (could be `ObjectId` or str if the
                parent is a silo, or None if that asset has no visual parent)
            3. list of asset doc that are in same depth and parent (list[dict])

        :param str coll_name: Avalon project collection name
        :rtype: list[tuple[int, Union[ObjectId, str, None], list[dict]]]
        """
        db = self.conn[self._db_name]  # type: MongoDatabase
        coll = db.get_collection(coll_name)  # type: MongoCollection

        _projection = {
            "name": True,
            "type": True,
            "silo": True,
            "data.trash": True,
            "data.tasks": True,
            "data.visualParent": True,
            "data.label": True
        }

        _assets = coll.find(
            {"type": "asset", "name": {"$exists": 1}},
            projection=_projection
        )
        _assets = sorted(_assets, key=lambda d: d['data']['label'])

        _episodes = coll.find(
            {"type": "episode", "name": {"$exists": 1}},
            projection=_projection
        )
        _episodes = sorted(_episodes, key=lambda d: d['name'])

        _sequences = coll.find(
            {"type": "sequence", "name": {"$exists": 1}},
            projection=_projection
        )
        _sequences = sorted(_sequences, key=lambda d: d['name'])

        _asset_types = coll.find(
            {"type": "asset_type", "name": {"$exists": 1}},
            projection=_projection
        )
        _asset_types = sorted(_asset_types, key=lambda d: d['name'])

        all_asset_docs = {d["_id"]: d for d in _assets + _episodes + _sequences + _asset_types}

        def count_depth(doc_):
            def depth(_d):
                p = _d["data"].get("visualParent")
                p_doc = all_asset_docs.get(p)
                yield 0 if p is None or p_doc is None else 1 + sum(depth(p_doc))

            return sum(depth(doc_))

        def group_key(doc_):
            """Key for sort/group assets by visual hierarchy depth
            :param dict doc_: Asset document
            :rtype: tuple[int, ObjectId] or tuple[int, str] or tuple[int, None]
            """
            _depth = count_depth(doc_)
            _vp = doc_["data"]["visualParent"] if _depth else doc_.get("silo")
            return _depth, _vp

        return [
            (depth, key, list(group))
            for (depth, key), group in
            groupby(
                sorted(all_asset_docs.values(), key=group_key),
                key=group_key
            )
        ]

    def get_silo_hidden(self, coll_name, silo_name):
        db = self.conn[self._db_name]  # type: MongoDatabase
        coll = db.get_collection(coll_name)  # type: MongoCollection

        silo = coll.find_one({'type': 'silo', 'name': silo_name})
        if silo:
            return silo.get('data', {}).get('trash', False)
        return False

    def join_project(self, coll_name):
        """
        :param str coll_name:
        :return: Update result
        :rtype: UpdateResult
        """
        _user = getpass.getuser()
        db = self.conn[self._db_name]  # type: MongoDatabase
        coll = db.get_collection(coll_name)  # type: MongoCollection

        result = coll.update_one(
            {"type": "project"},
            {"$addToSet": {f"data.role.{MEMBER_ROLE}": _user}}
        )

        return result

    def leave_project(self, coll_name):
        """
        :param str coll_name:
        :return: Update result
        :rtype: UpdateResult
        """
        _user = getpass.getuser()
        db = self.conn[self._db_name]  # type: MongoDatabase
        coll = db.get_collection(coll_name)  # type: MongoCollection

        result = coll.update_one(
            {"type": "project"},
            {"$pull": {f"data.role.{MEMBER_ROLE}": _user}}
        )

        return result


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
