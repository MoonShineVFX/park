
import os
import time
import logging
import getpass
from shotgun_api3 import Shotgun
from dataclasses import dataclass
from functools import singledispatch
from collections import MutableMapping
from typing import Union, Iterator, Callable, Set, overload
from rez.config import config as rezconfig
from .core import SuiteTool, AbstractScope
from .util import elide
from .exceptions import BackendError

# typing
ToolFilterCallable = Callable[[SuiteTool], bool]

log = logging.getLogger("allzpark")


parkconfig = rezconfig.plugins.command.park


def get_entrance(sg_server=None, api_key=None, script_name=None):
    """

    :param str sg_server:
    :param str api_key:
    :param str script_name:
    :return:
    :rtype: Entrance
    """
    sg_server = sg_server or os.getenv("SHOTGRID_SERVER")
    api_key = api_key or os.getenv("SHOTGRID_APIKEY")
    script_name = script_name or os.getenv("SHOTGRID_SCRIPT")

    if not sg_server:
        raise BackendError("ShotGrid server URL not given.")
    if not api_key:
        raise BackendError("ShotGrid API key not given.")
    if not script_name:
        raise BackendError("ShotGrid script-name not given.")

    return Entrance(sg_server=sg_server,
                    api_key=api_key,
                    script_name=script_name)


MANAGER_ROLE = "admin"


@dataclass(frozen=True)
class _Scope(AbstractScope):

    def exists(self) -> bool:
        return True

    def iter_children(self: "Entrance") -> Iterator["Project"]:
        """Iter child scopes
        """
        return iter_shotgrid_scopes(self)

    @overload
    def suite_path(self: "Entrance") -> str:
        ...

    @overload
    def suite_path(self: "Project") -> None:
        ...

    def suite_path(self):
        """Iter child scopes

        :type self: Entrance or Project
        :return:
        :rtype: Union[str, None]
        """
        return scope_suite_path(self)

    def make_tool_filter(
            self: Union["Entrance", "Project"]
    ) -> ToolFilterCallable:
        """
        :return:
        """
        return tool_filter_factory(self)

    def obtain_workspace(
            self: Union["Entrance", "Project"],
            tool: SuiteTool = None,
    ) -> Union[str, None]:
        """

        :param tool:
        :type tool: SuiteTool
        :type self: Entrance or Project or Asset or Task
        :return:
        :rtype: str or None
        """
        return obtain_workspace(self, tool)

    def additional_env(
            self: Union["Entrance", "Project"], tool: SuiteTool
    ) -> dict:
        """

        :param tool:
        :type tool: SuiteTool
        :type self: Entrance or Project or Asset or Task
        :return:
        :rtype: dict
        """
        if isinstance(self, Project):
            return {
                # for sg_sync
                "AVALON_PROJECTS": self.sg_project_root,
                "AVALON_PROJECT": self.tank_name,
                "SG_PROJECT_ID": self.id,
            }
        return dict()

    def current_user_roles(
            self: Union["Entrance", "Project", "Asset", "Task"]
    ) -> list:
        """
        :type self: Entrance or Project or Asset or Task
        :return:
        :rtype: list
        """
        return []

@dataclass(frozen=True)
class Entrance(_Scope):
    name = "sg_sync"
    upstream = None
    sg_server: str
    api_key: str
    script_name: str

    def __repr__(self):
        return f"Entrance(name={self.name}, sg_server={self.sg_server})"

    def __hash__(self):
        return hash(repr(self))


@dataclass(frozen=True)
class Project(_Scope):
    name: str
    upstream: Entrance
    roles: Set[str]
    code: str
    id: str
    tank_name: str
    sg_project_root: str

    def __repr__(self):
        return f"Project(" \
               f"name={self.name}, tank_name={self.tank_name}, " \
               f"upstream={self.upstream})"

    def __hash__(self):
        return hash(repr(self))


@singledispatch
def iter_shotgrid_scopes(scope):
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@iter_shotgrid_scopes.register
def _(scope: Entrance) -> Iterator[Project]:
    server = ShotGridConn(scope.sg_server,
                          scope.script_name,
                          scope.api_key,
                          entrance=scope)
    return iter_shotgrid_projects(server)


@iter_shotgrid_scopes.register
def _(scope: Project) -> tuple:
    log.debug(f"Endpoint reached: {elide(scope)}")
    return ()


@singledispatch
def scope_suite_path(scope):
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@scope_suite_path.register
def _(scope: Entrance) -> str:
    _ = scope
    return os.getenv("SHOTGRID_ENTRANCE_SUITE")


@scope_suite_path.register
def _(scope: Project) -> Union[str, None]:
    roots = parkconfig.suite_roots  # type: dict
    if not isinstance(roots, MutableMapping):
        raise BackendError("Invalid configuration, 'suite_roots' should be "
                           f"dict-like type value, not {type(roots)}.")

    shotgrid_suite_root = roots.get("shotgrid")
    if not shotgrid_suite_root:
        log.debug("No suite root for ShotGrid.")
        return

    suite_path = os.path.join(shotgrid_suite_root, scope.name)
    if not os.path.isdir(suite_path):
        log.debug(f"No suite root for ShotGrid project {scope.name}")
        return

    return suite_path


@singledispatch
def tool_filter_factory(scope) -> ToolFilterCallable:
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


@singledispatch
def obtain_workspace(scope, tool=None):
    _ = tool  # consume unused arg
    raise NotImplementedError(f"Unknown scope type: {type(scope)}")


@obtain_workspace.register
def _(scope: Entrance, tool: SuiteTool = None) -> None:
    _tool = f" for {tool.name!r}" if tool else ""
    log.debug(f"No workspace{_tool} in scope {elide(scope)}.")
    return None


@obtain_workspace.register
def _(scope: Project, tool: SuiteTool = None) -> Union[str, None]:
    _ = tool
    root = scope.sg_project_root
    root += "/" if ":" in root else ""
    # note: instead of checking root.endswith ':', just seeing if ':' in
    #   string let us also check if there is redundant path sep written
    #   in ShotGrid. We are on Windows.
    return os.path.join(root, scope.tank_name)


def iter_shotgrid_projects(server: "ShotGridConn"):
    for d in server.iter_valid_projects():
        roles = set()
        username = getpass.getuser()
        sg_user_ids = set([
            _["id"] for _ in (d.get("sg_cg_lead", []) + d.get("sg_pc", []))
        ])
        if username in server.find_human_logins(list(sg_user_ids)):
            roles.add(MANAGER_ROLE)
        # allow assigning personnel directly in package
        roles.add(username)

        yield Project(
            name=d["name"],
            upstream=server.entrance,
            roles=roles,
            code=d["code"],
            id=str(d["id"]),
            tank_name=d["tank_name"],
            sg_project_root=d["sg_project_root"]
        )


class ShotGridConn(object):
    """ShotGrid connector
    """
    def __init__(self, sg_server, script_name, api_key, entrance=None):
        """
        :param str sg_server: ShotGrid server URL
        :param str script_name: ShotGrid server URL
        :param str api_key: MongoDB connection timeout, default 1000
        :param entrance: The entrance scope that used to open this
            connection. Optional.
        :type entrance: Entrance or None
        """
        conn = Shotgun(sg_server,
                       script_name=script_name,
                       api_key=api_key,
                       connect=False)
        conn.config.timeout_secs = 1

        self.conn = conn
        self.sg_server = sg_server
        self.api_key = api_key
        self.script_name = script_name
        self.entrance = entrance

    def iter_valid_projects(self):
        fields = [
            "id",
            "code",
            "name",
            "tank_name",
            "sg_project_root",
            "sg_cg_lead",
            "sg_pc",
        ]
        filters = [
            ["archived", "is", False],
            ["is_template", "is", False],
            ["tank_name", "is_not", None],
            ["sg_project_root", "is_not", None],
        ]
        for doc in self.conn.find("Project", filters, fields):
            lower_name = doc["name"].lower()
            if lower_name.startswith("test"):
                continue
            yield doc

    def find_human_logins(self, user_ids):
        if not user_ids:
            return []
        fields = ["login"]
        filters = [["id", "in", user_ids]]
        docs = self.conn.find("HumanUser", filters=filters, fields=fields)
        return [d["login"] for d in docs]


def ping(server, retry=3):
    """Test shotgrid server connection with retry

    :param ShotGridConn server: An ShotGrid connection instance
    :param int retry: Max retry times, default 3
    :return: None
    :raises IOError: If not able to connect in given retry times
    """
    e = None
    for i in range(retry):
        try:
            t1 = time.time()
            server.conn.info()

        except Exception as e:
            log.error(f"Retrying..[{i}]")
            time.sleep(1)

        else:
            break

    else:
        raise IOError(f"ERROR: Couldn't connect to {server.sg_server!r} "
                      f"due to: {str(e)}")

    log.info(
        f"ShotGrid server {server.sg_server!r} connected, "
        f"delay {time.time() - t1:.3f}"
    )
