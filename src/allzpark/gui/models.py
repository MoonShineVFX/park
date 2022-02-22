
import os
import logging
from datetime import datetime
from itertools import zip_longest

from rez.packages import Variant
from rez.config import config as rezconfig
from sweet.core import RollingContext

from ._vendor.Qt5 import QtCore, QtGui
from ._vendor import qjsonmodel
from . import resources as res
from .. import util
from ..core import SuiteTool

log = logging.getLogger("allzpark")

allzparkconfig = rezconfig.plugins.command.park


class QSingleton(type(QtCore.QObject), type):
    """A metaclass for creating QObject singleton
    https://forum.qt.io/topic/88531/singleton-in-python-with-qobject
    https://bugreports.qt.io/browse/PYSIDE-1434?focusedCommentId=540135#comment-540135
    """
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(QSingleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


def parse_icon(pkg_root, pkg_icon_path, default_icon=None):
    pkg_icon_path = pkg_icon_path or ""
    try:
        fname = pkg_icon_path.format(
            root=pkg_root,
            width=32,
            height=32,
            w=32,
            h=32
        )

    except KeyError:
        fname = ""

    return QtGui.QIcon(fname or default_icon or ":/icons/box-seam.svg")


class BaseProxyModel(QtCore.QSortFilterProxyModel):

    def __init__(self, *args, **kwargs):
        super(BaseProxyModel, self).__init__(*args, **kwargs)
        self.setRecursiveFilteringEnabled(True)
        self.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)


class BaseItemModel(QtGui.QStandardItemModel):
    Headers = []

    def __init__(self, *args, **kwargs):
        super(BaseItemModel, self).__init__(*args, **kwargs)
        self.setColumnCount(len(self.Headers))

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole and section < len(self.Headers):
            return self.Headers[section]
        return super(BaseItemModel, self).headerData(
            section, orientation, role)

    def clear(self):
        """Clear model and header

        Removes all items (including header items) from the model and sets
        the number of rows and columns to zero.

        Note: Header view's section resize mode setting will be cleared
            altogether. Consider this action as a full reset.

        """
        super(BaseItemModel, self).clear()  # also clears header items, hence..
        self.setHorizontalHeaderLabels(self.Headers)

    def reset(self):
        """Remove all rows and set row count to zero

        This doesn't touch header.

        """
        self.removeRows(0, self.rowCount())
        self.setRowCount(0)

    def flags(self, index):
        """

        :param index:
        :type index: QtCore.QModelIndex
        :return:
        :rtype: QtCore.Qt.ItemFlags
        """
        return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable


class BaseScopeModel(BaseItemModel):
    ScopeRole = QtCore.Qt.UserRole + 10


class ToolsModel(BaseItemModel):
    ToolRole = QtCore.Qt.UserRole + 10
    Headers = ["Name"]

    def update_tools(self, tools):
        """

        :param tools:
        :type tools: list[SuiteTool]
        :return:
        """
        self.reset()

        def key(t):
            return order.index(t.name) if t.name in order else float("inf")
        order = allzparkconfig.tool_ordering or []  # type: list
        tools = sorted(tools, key=key)

        for tool in tools:
            label = f"{tool.metadata.label}"
            icon = parse_icon(
                tool.variant.root,
                tool.metadata.icon,
                ":/icons/joystick.svg"
            )
            item = QtGui.QStandardItem()
            item.setText(label)
            item.setIcon(icon)
            if tool.metadata.color:
                item.setBackground(
                    QtGui.QBrush(QtGui.QColor(tool.metadata.color))
                )
            item.setData(tool, self.ToolRole)

            self.appendRow(item)


class HistoryToolModel(BaseItemModel):
    ToolRole = QtCore.Qt.UserRole + 10
    Headers = ["Name", "Workspace"]

    def update_tools(self, tools):
        """

        :param tools:
        :type tools: list[SuiteTool]
        :return:
        """
        self.reset()

        for tool in tools:
            label = f"{tool.metadata.label} ({tool.ctx_name})"
            icon = parse_icon(
                tool.variant.root,
                tool.metadata.icon,
                ":/icons/joystick.svg"
            )
            item = QtGui.QStandardItem()
            item.setText(label)
            item.setIcon(icon)
            if tool.metadata.color:
                item.setBackground(
                    QtGui.QBrush(QtGui.QColor(tool.metadata.color))
                )
            item.setData(tool, self.ToolRole)

            scope_names = []
            scope = tool.scope
            while scope.upstream is not None:
                scope_names.append(scope.name)
                scope = scope.upstream

            work_item = QtGui.QStandardItem()
            work_item.setText(" / ".join(reversed(scope_names)))
            # todo: backend icon

            self.appendRow([item, work_item])


class _LocationIndicator(QtCore.QObject, metaclass=QSingleton):

    def __init__(self, *args, **kwargs):
        super(_LocationIndicator, self).__init__(*args, **kwargs)
        self._location_icon = [
            QtGui.QIcon(":/icons/person-circle.svg"),  # local
            QtGui.QIcon(":/icons/people-fill.svg"),  # non-local
            QtGui.QIcon(":/icons/people-fill-ok.svg"),  # released
        ]
        self._location_text = [
            "local", "non-local", "released"
        ]
        self._non_local = util.normpaths(*rezconfig.nonlocal_packages_path)
        self._release = util.normpath(rezconfig.release_packages_path)

    def compute(self, location):
        norm_location = util.normpath(location)
        is_released = int(norm_location == self._release) * 2
        is_nonlocal = int(norm_location in self._non_local)
        location_text = self._location_text[is_released or is_nonlocal]
        location_icon = self._location_icon[is_released or is_nonlocal]

        return location_text, location_icon


class JsonModel(qjsonmodel.QJsonModel):

    JsonRole = QtCore.Qt.UserRole + 1
    KeyRole = QtCore.Qt.UserRole + 2
    ValueRole = QtCore.Qt.UserRole + 3

    def __init__(self, parent=None):
        super(JsonModel, self).__init__(parent)
        self._headers = ("Key", "Value/[Count]")

    def setData(self, index, value, role):
        # Support copy/paste, but prevent edits
        return False

    def flags(self, index):
        flags = super(JsonModel, self).flags(index)
        return QtCore.Qt.ItemIsEditable | flags

    def data(self, index, role):
        if not index.isValid():
            return None

        item = index.internalPointer()
        parent = item.parent()

        if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
            if index.column() == 0:
                if parent.type is list:
                    return f"#{item.key:03} [{parent.childCount()}]"
                return item.key

            if index.column() == 1:
                if item.type is list:
                    return f"[{item.childCount()}]"
                return item.value

        elif role == self.JsonRole:
            return self.json(item)

        elif role == self.KeyRole:
            if parent.type is list:
                return parent.key
            return item.key

        elif role == self.ValueRole:
            return item.value

        return super(JsonModel, self).data(index, role)

    reset = qjsonmodel.QJsonModel.clear


class ResolvedPackagesModel(BaseItemModel):
    Headers = [
        "Package Name",
        "Version",
        "Local/Released",
    ]

    PackageRole = QtCore.Qt.UserRole + 10

    def pkg_icon_from_metadata(self, variant):
        metadata = getattr(variant, "_data", {})
        return parse_icon(variant.root, metadata.icon)

    def load(self, packages):
        """
        :param packages:
        :type packages: list[Variant]
        :return:
        """
        self.reset()
        indicator = _LocationIndicator()

        for pkg in packages:
            metadata = getattr(pkg, "_data", {})
            pkg_icon = parse_icon(pkg.root, metadata.get("icon"))

            loc_text, loc_icon = indicator.compute(pkg.resource.location)

            name_item = QtGui.QStandardItem(pkg.name)
            name_item.setIcon(pkg_icon)
            name_item.setData(pkg, self.PackageRole)

            version_item = QtGui.QStandardItem(str(pkg.version))

            location_item = QtGui.QStandardItem(loc_text)
            location_item.setIcon(loc_icon)

            self.appendRow([name_item, version_item, location_item])

    def pkg_path_from_index(self, index):
        if not index.isValid():
            return

        item_index = self.index(index.row(), 0)
        package = item_index.data(role=self.PackageRole)
        resource = package.resource

        if resource.key == "filesystem.package":
            return resource.filepath
        elif resource.key == "filesystem.variant":
            return resource.parent.filepath
        elif resource.key == "filesystem.package.combined":
            return resource.parent.filepath
        elif resource.key == "filesystem.variant.combined":
            return resource.parent.parent.filepath


class ResolvedEnvironmentModel(JsonModel):

    def __init__(self, parent=None):
        super(ResolvedEnvironmentModel, self).__init__(parent)
        self._placeholder_color = None
        self._headers = ("Key", "Value", "From")
        self._inspected = dict()
        self._sys_icon = QtGui.QIcon(":/icons/activity.svg")

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 3

    def set_placeholder_color(self, color):
        self._placeholder_color = color

    def _is_path_list(self, value):
        return os.pathsep in value and any(s in value for s in ("/", "\\"))

    def load(self, data):
        # Convert PATH-like environment variables to lists
        # for improved viewing experience
        for key, value in data.copy().items():
            if self._is_path_list(value):
                value = value.split(os.pathsep)
            data[key] = value

        super(ResolvedEnvironmentModel, self).load(data)

    def note(self, inspection):
        """
        :param inspection:
        :type inspection: list[tuple[Variant or str or None, str, str]]
        """
        for scope, key, value in inspection:
            if self._is_path_list(str(value)):
                for path in value.split(os.pathsep):
                    self._inspected[f"{key}/{path}"] = scope
            else:
                self._inspected[f"{key}/{value}"] = scope

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None

        item = index.internalPointer()
        parent = item.parent()

        if role == QtCore.Qt.DisplayRole:
            if index.column() == 2:
                if parent.type is list:
                    scope = self._inspected.get(f"{parent.key}/{item.value}")
                else:
                    scope = self._inspected.get(f"{item.key}/{item.value}")

                if isinstance(scope, Variant):
                    return scope.qualified_name
                elif isinstance(scope, str):
                    return f"({scope})"
                return None

        if role == QtCore.Qt.DecorationRole:
            if index.column() == 2:
                if parent.type is list:
                    scope = self._inspected.get(f"{parent.key}/{item.value}")
                else:
                    scope = self._inspected.get(f"{item.key}/{item.value}")

                if isinstance(scope, Variant):
                    metadata = getattr(scope, "_data", {})
                    return parse_icon(scope.root, metadata.get("icon"))
                elif isinstance(scope, str):
                    return self._sys_icon
                return None

        if role == QtCore.Qt.ForegroundRole:
            column = index.column()
            if (column == 1 and item.type is list) \
                    or (column == 0 and parent.type is list):
                return self._placeholder_color

        if role == QtCore.Qt.TextAlignmentRole:
            column = index.column()
            if column == 0 and parent.type is list:
                return QtCore.Qt.AlignRight

        return super(ResolvedEnvironmentModel, self).data(index, role)

    def flags(self, index):
        """
        :param QtCore.QModelIndex index:
        :rtype: QtCore.Qt.ItemFlags
        """
        if not index.isValid():
            return

        base_flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable

        if index.column() == 0:
            item = index.internalPointer()
            if item.parent().type is not list:
                return base_flags | QtCore.Qt.ItemIsEditable

        if index.column() == 1:
            item = index.internalPointer()
            if item.type is not list:
                return base_flags | QtCore.Qt.ItemIsEditable

        return base_flags


class ResolvedEnvironmentProxyModel(QtCore.QSortFilterProxyModel):

    def __init__(self, *args, **kwargs):
        super(ResolvedEnvironmentProxyModel, self).__init__(*args, **kwargs)
        self.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.setRecursiveFilteringEnabled(True)
        self._inverse = False

    def filter_by_key(self):
        self.setFilterRole(JsonModel.KeyRole)
        self.invalidateFilter()

    def filter_by_value(self):
        self.setFilterRole(JsonModel.ValueRole)
        self.invalidateFilter()

    def inverse_filter(self, value):
        self._inverse = bool(value)
        self.invalidateFilter()

    def filterAcceptsRow(self,
                         source_row: int,
                         source_parent: QtCore.QModelIndex) -> bool:
        accept = super(ResolvedEnvironmentProxyModel,
                       self).filterAcceptsRow(source_row, source_parent)
        if self._inverse:
            return not accept
        return accept


class _PendingContext:
    __getattr__ = (lambda self, k: "")
    success = usable = True
    package_paths = resolved_packages = resolved_ephemerals \
        = _package_requests = implicit_packages = package_filter \
        = package_orderers = []


class ContextDataModel(BaseItemModel):
    FieldNameRole = QtCore.Qt.UserRole + 10
    PlaceholderRole = QtCore.Qt.UserRole + 11
    Headers = [
        "Field",
        "Value",
    ]

    def __init__(self, *args, **kwargs):
        super(ContextDataModel, self).__init__(*args, **kwargs)
        self._show_attr = False  # don't reset this, for sticking toggle state
        self._placeholder_color = None
        self._context = None  # type: RollingContext or None
        self._in_diff = None  # type: RollingContext or None

    def reset(self):
        super(ContextDataModel, self).reset()
        self._context = None
        self._in_diff = None

    def pending(self):
        self.load(_PendingContext())  # noqa

    def load(self, context: RollingContext, diff=False):
        if diff and self._in_diff:
            log.critical("Context model already in diff mode.")
            return

        if diff:
            self._in_diff = context
        else:
            self.reset()
            self._context = context

        self.read("suite_context_name", "Context Name", "not saved/loaded")
        self.read("status", "Context Status", "no data")
        if not context.success:
            self.read("failure_description", "Why Failed")
        if not context.usable:
            self.read("err_on_get_tools", "Why Not Usable")
        self.read("created", "Resolved Date")
        self.read("requested_timestamp", "Ignore Packages After", "no timestamp set")
        self.read("package_paths")

        self.read("_package_requests", "Requests")
        self.read("resolved_packages")
        self.read("resolved_ephemerals")
        self.read("implicit_packages")
        self.read("package_filter")
        self.read("package_orderers")

        self.read("load_time")
        self.read("solve_time")
        self.read("num_loaded_packages", "Packages Queried")
        self.read("caching", "MemCache Enabled")
        self.read("from_cache", "Is MemCached Resolve")
        self.read("building", "Is Building")
        self.read("package_caching", "Cached Package Allowed")
        self.read("append_sys_path")

        self.read("parent_suite_path", "Suite Path")
        self.read("load_path", ".RXT Path")

        self.read("rez_version")
        self.read("rez_path")
        self.read("os", "OS")
        self.read("arch")
        self.read("platform")
        self.read("host")
        self.read("user")

    def find(self, field):
        for row in range(self.rowCount()):
            index = self.index(row, 0)
            if field == index.data(self.FieldNameRole):
                return index

    def read(self, field, pretty=None, placeholder=None):
        placeholder = placeholder or ""
        pretty = pretty or " ".join(w.capitalize() for w in field.split("_"))
        context = self._in_diff or self._context  # type: RollingContext
        assert context is not None

        # value
        icon = None
        value = getattr(context, field)

        if self._in_diff and value == getattr(self._context, field):
            return  # same value, no need to diff

        if field in ("created", "requested_timestamp"):
            if value:
                dt = datetime.fromtimestamp(value)
                value = dt.strftime("%b %d %Y %H:%M:%S")
            else:
                value = ""

        elif field == "status" and value != "":
            value = "broken" if context.broken else value.name
            value += "" if context.usable else " (but not usable)"

        elif field == "load_time" and value != "":
            value = f"{value:.02} secs"

        elif field == "solve_time" and value != "":
            actual_solve_time = value - context.load_time
            value = f"{actual_solve_time:.02} secs"

        elif field == "package_paths":
            indicator = _LocationIndicator()
            icon = [indicator.compute(v)[1] for v in value]

        elif field == "resolved_packages":
            indicator = _LocationIndicator()
            icon = [indicator.compute(pkg.resource.location)[1] for pkg in value]
            value = [pkg.qualified_name for pkg in value]

        elif field == "err_on_get_tools":
            field = ""

        # add row(s)

        if isinstance(value, list):
            icon = icon or [res.icon("dot.svg")] * len(value)
            value = [str(v) for v in value]

            field_item = QtGui.QStandardItem(pretty)
            field_item.setData(field, self.FieldNameRole)

            value_item = QtGui.QStandardItem()
            value_item.setText("" if value else placeholder or "")
            value_item.setData(not value, self.PlaceholderRole)
            value_item.setIcon(res.icon("plus.svg"))

            self.appendRow([field_item, value_item])

            for i, (value, ico_) in enumerate(zip_longest(value, icon)):
                field_item = QtGui.QStandardItem(f"#{i}")
                field_item.setData(True, self.PlaceholderRole)

                value_item = QtGui.QStandardItem(value)
                value_item.setIcon(ico_) if ico_ else None

                self.appendRow([field_item, value_item])

        else:
            if isinstance(value, bool):
                icon = icon or res.icon("check-ok.svg" if value else "slash-lg.svg")
                value = "yes" if value else "no"
            else:
                icon = icon or res.icon("dash.svg")
                value = str(value or "")

            field_item = QtGui.QStandardItem(pretty)
            field_item.setData(field, self.FieldNameRole)

            value_item = QtGui.QStandardItem()
            value_item.setText(value or placeholder)
            value_item.setData(not value, self.PlaceholderRole)
            value_item.setIcon(icon)

            self.appendRow([field_item, value_item])

    @QtCore.Slot(bool)  # noqa
    def on_pretty_shown(self, show_pretty: bool):
        self._show_attr = not show_pretty

    def set_placeholder_color(self, color):
        self._placeholder_color = color

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        # for viewing/copying context data (especially when the value is a
        # long path), item-editable flag is given. We re-implementing this
        # method is just to ensure the value unchanged after edit-mode ended.
        #
        self.dataChanged.emit(index, index, 1)  # trigger column width update
        return True

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return

        if role == QtCore.Qt.DisplayRole or role == QtCore.Qt.EditRole:
            column = index.column()
            if column == 0 and self._show_attr:
                return index.data(self.FieldNameRole)
            if column == 1 and role == QtCore.Qt.EditRole:
                return "" if index.data(self.PlaceholderRole) \
                    else super(ContextDataModel, self).data(index, role)

        if role == QtCore.Qt.ForegroundRole:
            if index.data(self.PlaceholderRole):
                return self._placeholder_color

        if role == QtCore.Qt.FontRole:
            column = index.column()
            if column == 0 and self._show_attr:
                return QtGui.QFont("JetBrains Mono")

        if role == QtCore.Qt.TextAlignmentRole:
            column = index.column()
            if column == 0:
                return QtCore.Qt.AlignRight

        return super(ContextDataModel, self).data(index, role)

    def flags(self, index):
        """
        :param QtCore.QModelIndex index:
        :rtype: QtCore.Qt.ItemFlags
        """
        if not index.isValid():
            return
        column = index.column()

        base_flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        if (column == 0 and self._show_attr) or column == 1:
            return base_flags | QtCore.Qt.ItemIsEditable
        return base_flags
