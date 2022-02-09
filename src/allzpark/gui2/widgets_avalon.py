
import logging
from typing import List, Union
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets
from ..backend_avalon import Entrance, Project, Asset, Task, MEMBER_ROLE
from ..util import singledispatchmethod, elide
from ..core import AbstractScope
from .widgets import SlidePageWidget
from .models import BaseScopeModel

log = logging.getLogger(__name__)


ASSET_MUST_BE_TASKED = True


class AvalonWidget(QtWidgets.QWidget):
    icon_path = ":/icons/avalon.svg"
    tools_requested = QtCore.Signal(AbstractScope)
    workspace_changed = QtCore.Signal(AbstractScope)

    def __init__(self, *args, **kwargs):
        super(AvalonWidget, self).__init__(*args, **kwargs)

        project_list = ProjectListWidget()
        asset_tree = AssetTreeWidget()

        asset_page = QtWidgets.QWidget()
        current_project = ScopeLineLabel("current project..")
        home = QtWidgets.QPushButton()
        tasks = QtWidgets.QComboBox()
        only_tasked = QtWidgets.QCheckBox("Show Tasked Only")

        layout = QtWidgets.QGridLayout(asset_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(home, 0, 0, 1, 1)
        layout.addWidget(current_project, 0, 1, 1, 6)
        layout.addWidget(only_tasked, 1, 0, 1, 3)
        layout.addWidget(tasks, 1, 3, 1, 4)
        layout.addWidget(asset_tree, 2, 0, 1, 7)

        slider = SlidePageWidget()
        slider.addWidget(project_list)
        slider.addWidget(asset_page)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(slider)

        home.clicked.connect(self._on_home_clicked)
        project_list.scope_selected.connect(self.workspace_changed.emit)
        asset_tree.scope_selected.connect(self._on_asset_selected)
        asset_tree.deselected.connect(self._on_asset_deselected)
        tasks.currentTextChanged.connect(asset_tree.on_task_selected)
        only_tasked.stateChanged.connect(asset_tree.on_asset_filtered)

        self._entrance = None
        self._projects = project_list
        self._assets = asset_tree
        self._tasks = tasks
        self._slider = slider
        self._page = 0
        self._current_project = current_project
        self._current_scope = None

    def _on_home_clicked(self):
        assert self._entrance is not None
        self.workspace_changed.emit(self._entrance)

    def _on_asset_deselected(self):
        if not isinstance(self._current_scope, Project):
            self._current_scope = self._current_scope.project
            self._current_asset.setText("")
            self._current_task.setText("")
            self.tools_requested.emit(self._current_scope)

    def _on_asset_selected(self, asset: Asset):
        current = self._tasks.currentText()
        tasks = asset.iter_children()
        task = next((t for t in tasks if t.name == current), None)
        if task:
            self.workspace_changed.emit(task)
        else:
            log.warning(f"No matched task for {asset.name!r}.")
            self.workspace_changed.emit(asset)

    def set_page(self, page):
        current = self._slider.currentIndex()
        if current == page and self._page == page:
            return

        direction = "right" if page > current else "left"
        self._page = page
        self._slider.slide_view(page, direction=direction)

    @singledispatchmethod
    def enter_workspace(self, scope):
        raise NotImplementedError(f"Unknown scope {elide(scope)!r}")

    @enter_workspace.register
    def _(self, scope: Entrance):
        self._entrance = scope
        self.set_page(0)

    @enter_workspace.register
    def _(self, scope: Project):
        self._current_scope = scope
        self._current_project.setText(scope.name)
        self.set_page(1)
        self._tasks.clear()
        self._tasks.addItems(scope.tasks)
        self.tools_requested.emit(scope)

    @enter_workspace.register
    def _(self, scope: Asset):
        self._current_scope = scope
        self.tools_requested.emit(scope)

    @enter_workspace.register
    def _(self, scope: Task):
        self._current_scope = scope
        self.tools_requested.emit(scope)

    def update_workspace(
            self, scopes: Union[List[Project], List[Asset], List[Task]]
    ) -> None:

        if not scopes:
            log.debug("No scopes to update.")
            return
        upstream = scopes[0].upstream  # take first scope as sample

        if isinstance(upstream, Entrance):
            self._projects.model().refresh(scopes)

        elif isinstance(upstream, Project):
            self._assets.model().refresh(scopes)

        elif isinstance(upstream, Asset):
            pass

        elif isinstance(upstream, Task):
            raise NotImplementedError(f"Task {elide(upstream)!r} shouldn't "
                                      f"have downstream scope.")
        else:
            raise NotImplementedError(f"Unknown upstream {elide(upstream)!r}")


class ScopeLineLabel(QtWidgets.QLineEdit):

    def __init__(self, placeholder="", *args, **kwargs):
        super(ScopeLineLabel, self).__init__(*args, **kwargs)
        self.setReadOnly(True)
        self.setPlaceholderText(placeholder)


class ProjectListWidget(QtWidgets.QWidget):
    scope_selected = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super(ProjectListWidget, self).__init__(*args, **kwargs)

        search_bar = QtWidgets.QLineEdit()
        search_bar.setPlaceholderText("search projects..")

        # todo: join/leave project

        model = ProjectListModel()
        view = QtWidgets.QListView()
        view.setModel(model)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(search_bar)
        layout.addWidget(view)

        view.clicked.connect(self._on_item_clicked)

        self._view = view
        self._model = model

    def model(self):
        return self._model

    def _on_item_clicked(self, index):
        scope = index.data(BaseScopeModel.ScopeRole)
        self.scope_selected.emit(scope)


class AssetTreeWidget(QtWidgets.QWidget):
    scope_selected = QtCore.Signal(AbstractScope)
    deselected = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super(AssetTreeWidget, self).__init__(*args, **kwargs)

        search_bar = QtWidgets.QLineEdit()
        search_bar.setPlaceholderText("search assets..")

        model = AssetTreeModel()
        proxy = AssetTreeProxyModel()
        proxy.setSourceModel(model)
        view = QtWidgets.QTreeView()
        view.setSelectionMode(view.SingleSelection)
        view.setModel(proxy)
        selection = view.selectionModel()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(search_bar)
        layout.addWidget(view)

        model.modelAboutToBeReset.connect(proxy.invalidate)
        selection.currentChanged.connect(self._on_current_changed)
        selection.selectionChanged.connect(self._on_selection_changed)
        search_bar.textChanged.connect(self._on_asset_searched)

        self._view = view
        self._model = model
        self._proxy = proxy

    def model(self):
        return self._model

    def on_task_selected(self, task_name):
        self._model.set_task(task_name)
        self._proxy.invalidate()

        index = self._view.currentIndex()
        if not index.isValid():
            self.deselected.emit()
        else:
            scope = index.data(BaseScopeModel.ScopeRole)
            self.scope_selected.emit(scope)  # for update task

    def on_asset_filtered(self, enabled):
        self._proxy.set_filter_by_task(bool(enabled))
        self._proxy.invalidate()

        index = self._view.currentIndex()
        if not index.isValid():
            self.deselected.emit()

    def _on_asset_searched(self, text):
        self._proxy.setFilterRegExp(text)

    def _on_current_changed(self, index, _):
        if index.isValid():
            index = self._proxy.mapToSource(index)
            scope = index.data(BaseScopeModel.ScopeRole)
            if is_asset_tasked(scope, self._model.task()):
                self.scope_selected.emit(scope)
            else:
                self._view.clearSelection()

    def _on_selection_changed(self, selected, _):
        if not selected.indexes():
            self.deselected.emit()


class ProjectListModel(BaseScopeModel):
    Headers = ["Name"]

    def refresh(self, scopes):
        self.reset()

        for project in scopes:
            # todo: this should be toggleable
            if project.is_active \
                    and (not project.roles or MEMBER_ROLE in project.roles):
                item = QtGui.QStandardItem()
                item.setText(project.name)
                item.setData(project, self.ScopeRole)

                self.appendRow(item)


class AssetTreeModel(BaseScopeModel):
    Headers = ["Name"]

    def __init__(self, *args, **kwargs):
        super(AssetTreeModel, self).__init__(*args, **kwargs)
        self._task = None

    def task(self):
        return self._task

    def set_task(self, name):
        self._task = name

    def refresh(self, scopes):
        self.reset()

        _asset_items = dict()
        for asset in scopes:
            if not asset.is_hidden:
                item = QtGui.QStandardItem()
                item.setText(asset.name)
                item.setData(asset, self.ScopeRole)

                _asset_items[asset.name] = item

                if asset.parent is None:
                    self.appendRow(item)

                else:
                    parent = _asset_items[asset.parent.name]
                    parent.appendRow(item)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        """
        :param QtCore.QModelIndex index:
        :param int role:
        :return:
        """
        if not index.isValid():
            return

        if role == QtCore.Qt.FontRole:
            scope = index.data(self.ScopeRole)  # type: Asset
            if not scope.is_silo and not is_asset_tasked(scope, self._task):
                font = QtGui.QFont()
                font.setStrikeOut(True)
                return font

        return super(AssetTreeModel, self).data(index, role)

    def flags(self, index):
        if not index.isValid():
            return

        scope = index.data(self.ScopeRole)  # type: Asset
        if is_asset_tasked(scope, self._task):
            return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        else:
            return QtCore.Qt.ItemIsEnabled  # not selectable


class AssetTreeProxyModel(QtCore.QSortFilterProxyModel):

    def __init__(self, *args, **kwargs):
        super(AssetTreeProxyModel, self).__init__(*args, **kwargs)
        self.setRecursiveFilteringEnabled(True)
        self.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self._filter_by_task = False

    def set_filter_by_task(self, enabled: bool):
        self._filter_by_task = enabled

    def filterAcceptsRow(self, source_row, source_parent):
        """
        :param int source_row:
        :param QtCore.QModelIndex source_parent:
        :rtype: bool
        """
        accepted = super(AssetTreeProxyModel, self).filterAcceptsRow(
            source_row, source_parent
        )
        if accepted and self._filter_by_task:
            model = self.sourceModel()  # type: AssetTreeModel
            index = model.index(source_row, 0, source_parent)
            scope = index.data(AssetTreeModel.ScopeRole)
            return \
                not scope.is_silo \
                and is_asset_tasked(scope, model.task())

        return accepted


def is_asset_tasked(scope: Asset, task_name: str) -> bool:
    if ASSET_MUST_BE_TASKED:
        return task_name in scope.tasks
    return not scope.tasks or task_name in scope.tasks
