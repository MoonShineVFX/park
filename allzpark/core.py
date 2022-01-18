
from dataclasses import dataclass
from rez.suite import Suite
from rez.packages import Variant
from rez.resolved_context import ResolvedContext


@dataclass
class SuiteTool:
    name: str
    icon: str
    label: str
    alias: str
    ctx_name: str
    variant: Variant


def find_suite(name, branch):
    """Find one saved suite in specific branch

    :param str name:
    :param str branch:
    :return:
    :rtype: ReadOnlySuite
    """
    # todo: suite storage roots should be defined in config


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
    load = _invalid_operation

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
                icon="",  # todo: get data from package
                label="",
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
