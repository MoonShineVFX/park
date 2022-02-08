
import logging
from typing import Set, Union, Iterator, Callable
from dataclasses import dataclass
from rez.suite import Suite
from rez.packages import Variant
from rez.resolved_context import ResolvedContext
from .exceptions import BackendError

log = logging.getLogger(__name__)


def _load_backends():
    from . import backend_avalon as avalon

    def try_avalon_backend() -> avalon.Entrance:
        scope = avalon.get_entrance()
        avalon.ping(
            avalon.AvalonMongo(scope.uri, scope.timeout, entrance=scope)
        )
        return scope

    return [
        (avalon.Entrance.name, try_avalon_backend),
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

    if available_backends:
        return available_backends

    raise BackendError("No available backend.")


def load_suite(path):
    """Load one saved suite from path

    :param str path:
    :return:
    :rtype: ReadOnlySuite or None
    """
    return ReadOnlySuite.load(path)


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


@dataclass
class ToolMetadata:
    label: str
    icon: str
    color: str
    hidden: bool
    required_roles: Set[str]


@dataclass
class SuiteTool:
    name: str
    alias: str
    ctx_name: str
    variant: Variant

    @property
    def context(self):
        return self.variant.context

    @property
    def metadata(self):
        data = getattr(self.variant, "_data", {})
        return ToolMetadata(
            label=data.get("label", self.variant.name),
            icon=data.get("icon", ":/icons/general-tool.svg"),
            color=data.get("color"),
            hidden=data.get("hidden", False),
            required_roles=set(data.get("required_roles", [])),
        )


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

    def _iter_tools(_scope):
        try:
            suite_path = _scope.suite_path()
        except BackendError as e:
            log.error(str(e))
        else:
            if suite_path:
                suite = load_suite(suite_path)
                for _tool in suite.iter_tools():
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


class _Suite(Suite):
    @classmethod
    def from_dict(cls, d):
        s = cls.__new__(cls)
        s.load_path = None
        s.tools = None
        s.tool_conflicts = None
        s.contexts = d["contexts"]
        if s.contexts:
            s.next_priority = max(x["priority"]
                                  for x in s.contexts.values()) + 1
        else:
            s.next_priority = 1
        return s


class ReadOnlySuite(_Suite):
    """A Read-Only SweetSuite"""

    def __init__(self):
        super(ReadOnlySuite, self).__init__()
        self._is_live = True

    @classmethod
    def from_dict(cls, d):
        """Parse dict into suite
        :return:
        :rtype: ReadOnlySuite
        """
        s = super(ReadOnlySuite, cls).from_dict(d)
        s._is_live = d.get("live_resolve", False)
        return s

    def _invalid_operation(self, *_, **__):
        raise RuntimeError("Invalid operation, this suite is Read-Only.")

    add_context = _invalid_operation
    remove_context = _invalid_operation
    set_context_prefix = _invalid_operation
    remove_context_prefix = _invalid_operation
    set_context_suffix = _invalid_operation
    remove_context_suffix = _invalid_operation
    bump_context = _invalid_operation
    hide_tool = _invalid_operation
    unhide_tool = _invalid_operation
    alias_tool = _invalid_operation
    unalias_tool = _invalid_operation
    save = _invalid_operation

    def context(self, name):
        """Get a context.
        :param name:
        :return:
        """
        data = self._context(name)
        context = data.get("context")
        if context:
            return context

        assert self.load_path
        context_path = self._context_path(name, self.load_path)
        context = ResolvedContext.load(context_path)
        if self._is_live:
            context = re_resolve_rxt(context)
        else:
            data["context"] = context
            data["loaded"] = True
        return context

    def is_live(self):
        return self._is_live

    def iter_tools(self):
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
            )

    # Exposing protected member that I'd like to use.
    flush_tools = Suite._flush_tools


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
    :rtype: ResolvedContext
    :raises AssertionError: If no context.load_path (not loaded from .rxt)
    """
    assert context.load_path, "Not a loaded context."
    rxt = context
    return ResolvedContext(
        package_requests=rxt.requested_packages(),
        timestamp=rxt.requested_timestamp,
        package_paths=rxt.package_paths,
        package_filter=rxt.package_filter,
        package_orderers=rxt.package_orderers,
        building=rxt.building,
    )
