
import logging
import functools
import traceback
from typing import Set, Union, Iterator, Callable
from dataclasses import dataclass
from rez.packages import Variant
from rez.config import config as rezconfig
from rez.package_repository import package_repository_manager
from sweet.core import RollingContext, SweetSuite
from .exceptions import BackendError

log = logging.getLogger("allzpark")


def _load_backends():

    def try_avalon_backend():
        from . import backend_avalon as avalon

        scope = avalon.get_entrance()
        avalon.ping(
            avalon.AvalonMongo(scope.uri, scope.timeout, entrance=scope)
        )
        return scope  # type: avalon.Entrance

    def try_sg_sync_backend():
        from . import backend_sg_sync as shotgrid

        scope = shotgrid.get_entrance()
        shotgrid.ping(
            shotgrid.ShotGridConn(scope.sg_server,
                                  scope.script_name,
                                  scope.api_key,
                                  entrance=scope)
        )
        return scope  # type: shotgrid.Entrance

    return [
        ("avalon", try_avalon_backend),
        ("sg_sync", try_sg_sync_backend),
        # could be ftrack, or shotgrid, could be...
    ]


def init_backends(no_warning=False):
    """

    :param bool no_warning:
    :return: A list of available backend name and entrance object pair
    :rtype: list[tuple[str, Entrance]]
    """
    possible_backends = _load_backends()
    available_backends = []

    for name, entrance_getter in possible_backends:
        log.info(f"> Init backend {name!r}..")
        try:
            entrance = entrance_getter()
        except Exception as e:
            if no_warning:
                continue
            log.warning(
                f"Cannot get entrance from backend {name!r}: {str(e)}"
            )
        else:
            available_backends.append((name, entrance))
            log.info(f"- Backend {name!r} connected.")

    if available_backends:
        return available_backends

    raise BackendError("* No available backend.")


def load_suite(path):
    """Load one saved suite from path

    :param str path:
    :return:
    :rtype: ReadOnlySuite or None
    """
    log.debug(f"Loading suite: {path}")
    suite = ReadOnlySuite.load(path)
    if suite.is_live():
        log.debug(f"Re-resolve contexts in suite..")
        suite.re_resolve_rxt_contexts()

    return suite


class AbstractScope:
    name: str
    upstream: Union["AbstractScope", None]

    def exists(self) -> bool:
        """Query backend to check if this scope exists"""
        raise NotImplementedError

    def iter_children(self) -> Iterator["AbstractScope"]:
        """Iter child scopes"""
        raise NotImplementedError

    def suite_path(self) -> Union[str, None]:
        """Returns a load path of a suite that is for this scope, if any"""
        raise NotImplementedError

    def make_tool_filter(self) -> Callable[["SuiteTool"], bool]:
        """Returns a callable for filtering tools

        Example:

        >>> @dataclass(frozen=True)
        ... class ProjectScope(AbstractScope):  # noqa
        ...     def make_tool_filter(self):
        ...         def _filter(tool: SuiteTool) -> bool:
        ...             required_roles = tool.metadata.required_roles
        ...             return (
        ...                 not tool.metadata.hidden
        ...                 and self.roles.intersection(required_roles)  # noqa
        ...             )
        ...         return _filter

        """
        raise NotImplementedError

    def obtain_workspace(self, tool: "SuiteTool") -> Union[str, None]:
        """Returns a working directory for this scope, if allowed"""
        raise NotImplementedError

    def additional_env(self, tool: "SuiteTool") -> dict:
        """Returns environ that will be applied to the tool context"""
        raise NotImplementedError

    def generate_breadcrumb(self) -> dict:
        return {}


def generate_tool_breadcrumb(tool: "SuiteTool") -> Union[dict, None]:
    breadcrumb = tool.scope.generate_breadcrumb()
    if not breadcrumb:
        return
    breadcrumb["tool_alias"] = tool.alias
    return breadcrumb


def get_tool_from_breadcrumb(
        breadcrumb: dict,
        backends: dict
) -> Union["SuiteTool", None]:
    """
    """
    log.debug(f"Parsing breadcrumb: {breadcrumb}")

    backend_name = breadcrumb.get("entrance")
    if not backend_name:
        log.error("No backend found in breadcrumb.")
        return

    tool_alias = breadcrumb.get("tool_alias")
    if not tool_alias:
        log.error("No tool alias found in breadcrumb.")
        return

    backend = backends.get(backend_name)
    if not backend:
        log.error(f"Backend {backend_name!r} is currently not available.")
        return

    if not callable(getattr(backend, "get_scope_from_breadcrumb", None)):
        log.critical(f"Backend {backend_name!r} doesn't have "
                     "'get_scope_from_breadcrumb()' implemented.")
        return

    scope = backend.get_scope_from_breadcrumb(breadcrumb)  # type: AbstractScope
    if scope is None:
        log.warning(f"Unable to get scope from backend: {breadcrumb}")
        return
    log.debug(f"Searching tool {tool_alias!r} in scope {scope}")

    tool = None
    for tool in _tools_iter(scope, caching=True):
        if tool.alias == tool_alias:
            break
    else:
        log.debug("No matched tool found in scope.")

    return tool


@dataclass(frozen=True)
class ToolMetadata:
    label: str
    icon: str
    color: str
    hidden: bool
    required_roles: Set[str]
    no_console: bool
    start_new_session: bool
    remember_me: bool


@dataclass(frozen=True)
class SuiteTool:
    name: str
    alias: str
    ctx_name: str
    variant: Variant
    scope: Union[AbstractScope, None]

    @property
    def context(self) -> RollingContext:
        return self.variant.context

    @property
    def metadata(self) -> ToolMetadata:
        data = getattr(self.variant, "_data", {}).copy()
        tool = data.get("override", {}).get(self.name)  # e.g. pre tool icon
        data.update(tool or {})
        return ToolMetadata(
            label=data.get("label", self.variant.name),
            icon=data.get("icon"),
            color=data.get("color"),
            hidden=data.get("hidden", False),
            required_roles=set(data.get("required_roles", [])),
            no_console=data.get("no_console", True),
            start_new_session=data.get("start_new_session", True),
            remember_me=data.get("remember_me", True),
        )


def cache_clear():
    log.debug("Cleaning caches..")

    # clear cached packages
    for path in rezconfig.packages_path:
        log.debug(f"Cleaning package repository cache: {path}")
        repo = package_repository_manager.get_repository(path)
        repo.clear_caches()

    # clear cached suites and tools
    log.debug("Cleaning cached suites and tools")
    _load_suite.cache_clear()
    list_tools.cache_clear()

    log.debug("Core cache cleared.")


def _tools_iter(scope, filtering=None, caching=False):
    _get_suite = _load_suite if caching else load_suite

    def _iter_tools(_scope):
        try:
            suite_path = _scope.suite_path()
        except BackendError as e:
            log.error(str(e))
        else:
            if suite_path:
                try:
                    suite = _get_suite(suite_path)
                except Exception as e:
                    log.error(traceback.format_exc())
                    log.error(f"Failed load suite: {str(e)}")
                else:
                    for _tool in suite.iter_tools(scope=scope):
                        yield _tool
        if _scope.upstream is not None:
            for _tool in _iter_tools(_scope.upstream):
                yield _tool

    if filtering is False:
        func = None
    elif callable(filtering):
        func = filtering
    else:
        func = scope.make_tool_filter()

    for tool in filter(func, _iter_tools(scope)):
        yield tool


@functools.lru_cache(maxsize=None)
def _load_suite(path):
    return load_suite(path)


@functools.lru_cache(maxsize=None)
def list_tools(scope, filtering=None):
    """List tools within scope and upstream scopes with lru cached

    :param scope: where to iter tools from
    :param filtering: If None, the default, tools will be filtered by
        the scope. If False, no filtering. Or if a callable is given,
        filtering tools with it instead.
    :type scope: AbstractScope
    :type filtering: bool or Callable or None
    :rtype: Iterator[SuiteTool]
    """
    return list(_tools_iter(scope, filtering, caching=True))


def iter_tools(scope, filtering=None):
    """Iterate tools within scope and upstream scopes

    :param scope: where to iter tools from
    :param filtering: If None, the default, tools will be filtered by
        the scope. If False, no filtering. Or if a callable is given,
        filtering tools with it instead.
    :type scope: AbstractScope
    :type filtering: bool or Callable or None
    :rtype: Iterator[SuiteTool]
    """
    return _tools_iter(scope, filtering, caching=False)


class ReadOnlySuite(SweetSuite):
    """A Read-Only SweetSuite"""

    def _invalid_operation(self, *_, **__):
        raise RuntimeError("Invalid operation, this suite is Read-Only.")

    _update_context = SweetSuite.update_context
    add_context = \
        update_context = \
        remove_context = \
        rename_context = \
        set_context_prefix = \
        remove_context_prefix = \
        set_context_suffix = \
        remove_context_suffix = \
        bump_context = \
        hide_tool = \
        unhide_tool = \
        alias_tool = \
        unalias_tool = \
        set_live = \
        set_description = \
        save = _invalid_operation

    def re_resolve_rxt_contexts(self):
        """Re-resolve all contexts that loaded from .rxt files
        :return:
        """
        for name in list(self.contexts.keys()):
            context = self.context(name)
            if context.load_path:
                self._update_context(name, re_resolve_rxt(context))

    def iter_tools(self, scope=None):
        """Iter tools in this suite
        :return:
        :rtype: collections.Iterator[SuiteTool]
        """
        for alias, entry in self.get_tools().items():
            yield SuiteTool(
                name=entry["tool_name"],
                alias=entry["tool_alias"],
                ctx_name=entry["context_name"],
                variant=entry["variant"],
                scope=scope,
            )


def re_resolve_rxt(context):
    """Re-resolve context loaded from .rxt file

    This takes following entries from input context to resolve a new one:
        - package_requests
        - timestamp
        - package_paths
        - package_filters
        - package_orderers
        - building

    :param context: .rxt loaded context
    :type context: ResolvedContext
    :return: new resolved context
    :rtype: RollingContext
    :raises AssertionError: If no context.load_path (not loaded from .rxt)
    """
    assert context.load_path, "Not a loaded context."
    rxt = context
    return RollingContext(
        package_requests=rxt.requested_packages(),
        timestamp=rxt.requested_timestamp,
        package_paths=rxt.package_paths,
        package_filter=rxt.package_filter,
        package_orderers=rxt.package_orderers,
        building=rxt.building,
    )
