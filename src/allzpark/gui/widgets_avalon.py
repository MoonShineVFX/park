
import logging
from typing import List, Union
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets
from ..backend_avalon import Entrance, Project, Asset, Task, MEMBER_ROLE
from ..util import elide
from ..core import AbstractScope
from .widgets import SlidePageWidget, ScopeLineLabel
from .models import BaseScopeModel, BaseProxyModel

log = logging.getLogger("allzpark")


ASSET_MUST_BE_TASKED = True


class AvalonWidget(QtWidgets.QWidget):
    """Avalon backend GUI

    Behaviors should be expected:

        * Project Page
            - select a project will side to asset page
            - able to join/leave project (filtering projects from view)
            - able to show *all projects* with a toggle (disable filtering)

        * Asset Page
            - tools should be updated whenever the asset selection changes
            - if asset has no selection, change to project scope and tools
            - able to use task to filter asset

    """
    icon_path = ":/icons/avalon-logomark.svg"
    tools_requested = QtCore.Signal(AbstractScope)
    workspace_changed = QtCore.Signal(AbstractScope)
    workspace_refreshed = QtCore.Signal(AbstractScope)

    def __init__(self, *args, **kwargs):
        super(AvalonWidget, self).__init__(*args, **kwargs)

        label = QtWidgets.QLabel("Avalon")
        label.setObjectName("BackendLabel")

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
        layout.addWidget(label)
        layout.addWidget(slider)

        home.clicked.connect(self._on_home_clicked)
        project_list.scope_selected.connect(self.workspace_changed.emit)
        project_list.filter_toggled.connect(self._on_project_filtered)
        project_list.refresh_clicked.connect(self._on_project_refreshed)
        asset_tree.scope_changed.connect(self._on_asset_changed)
        tasks.currentTextChanged.connect(asset_tree.on_task_selected)
        only_tasked.stateChanged.connect(asset_tree.on_asset_filtered)

        self.__inited = False
        self._entrance = None  # type: Entrance or None
        self._projects = project_list
        self._assets = asset_tree
        self._tasks = tasks
        self._slider = slider
        self._page = 0
        self._current_project = current_project

    def _on_home_clicked(self):
        assert self._entrance is not None
        self.workspace_changed.emit(self._entrance)

    def _on_project_filtered(self, joined):
        scope = self._entrance
        scope.kwargs["joined"] = bool(joined)
        self.workspace_refreshed.emit(scope)

    def _on_project_refreshed(self):
        self.workspace_refreshed.emit(self._entrance)

    def _on_asset_changed(self, scope: Union[Asset, Project]):
        if isinstance(scope, Project):
            self.tools_requested.emit(scope)
            return

        asset = scope
        current = self._tasks.currentText()
        tasks = asset.iter_children()
        task = next((t for t in tasks if t.name == current), None)
        if task:
            self.tools_requested.emit(task)
        else:
            log.warning(f"No matched task for {asset.name!r}.")
            self.tools_requested.emit(asset)

    def set_page(self, page):
        current = self._slider.currentIndex()
        if current == page and self._page == page:
            return

        direction = "right" if page > current else "left"
        self._page = page
        self._slider.slide_view(page, direction=direction)

    def enter_workspace(self,
                        scope: Union[Entrance, Project],
                        backend_changed: bool) -> None:
        if isinstance(scope, Entrance):
            self._entrance = scope
            if backend_changed and self.__inited:
                return
            self.set_page(0)

        elif isinstance(scope, Project):
            self._current_project.setText(scope.name)
            self.set_page(1)
            self._tasks.clear()
            self._tasks.addItems(scope.tasks)
        else:
            return

        self.tools_requested.emit(scope)
        self.workspace_refreshed.emit(scope)

    def update_workspace(
            self, scopes: Union[List[Project], List[Asset], List[Task]]
    ) -> None:

        if not scopes:
            log.debug("No scopes to update.")
            return
        upstream = scopes[0].upstream  # take first scope as sample

        if isinstance(upstream, Entrance):
            self._assets.model().reset()
            self._projects.model().refresh(scopes)
            self.__inited = True

        elif isinstance(upstream, Project):
            self._assets.model().refresh(scopes)
            self._assets.model().set_task(self._tasks.currentText())

        elif isinstance(upstream, Asset):
            pass

        elif isinstance(upstream, Task):
            raise NotImplementedError(f"Task {elide(upstream)!r} shouldn't "
                                      f"have downstream scope.")
        else:
            raise NotImplementedError(f"Unknown upstream {elide(upstream)!r}")


class ProjectListWidget(QtWidgets.QWidget):
    refresh_clicked = QtCore.Signal()
    filter_toggled = QtCore.Signal(bool)
    scope_selected = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super(ProjectListWidget, self).__init__(*args, **kwargs)
        self.setObjectName("AvalonProjectView")

        top_bar = QtWidgets.QWidget()
        top_bar.setObjectName("ButtonBelt")
        refresh_btn = QtWidgets.QPushButton()
        refresh_btn.setObjectName("RefreshButton")
        search_bar = QtWidgets.QLineEdit()
        search_bar.setPlaceholderText("search projects..")
        filter_btn = QtWidgets.QPushButton()
        filter_btn.setObjectName("DarkSwitch")
        filter_btn.setCheckable(True)
        filter_btn.setChecked(True)  # the default defined in backend module

        model = ProjectListModel()
        proxy = BaseProxyModel()
        proxy.setSourceModel(model)
        view = QtWidgets.QListView()
        view.setModel(proxy)

        layout = QtWidgets.QHBoxLayout(top_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(refresh_btn)
        layout.addWidget(search_bar, stretch=True)
        layout.addWidget(filter_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(top_bar)
        layout.addWidget(view)

        view.clicked.connect(self._on_item_clicked)
        search_bar.textChanged.connect(self._on_project_searched)
        filter_btn.toggled.connect(self.filter_toggled)
        refresh_btn.clicked.connect(self.refresh_clicked)

        self._view = view
        self._proxy = proxy
        self._model = model

    def model(self):
        return self._model

    def _on_item_clicked(self, index):
        scope = index.data(BaseScopeModel.ScopeRole)
        self.scope_selected.emit(scope)

    def _on_project_searched(self, text):
        self._proxy.setFilterRegExp(text)


class AssetTreeWidget(QtWidgets.QWidget):
    scope_changed = QtCore.Signal(AbstractScope)

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

        selection.selectionChanged.connect(self._on_selection_changed)
        search_bar.textChanged.connect(self._on_asset_searched)
        model.modelAboutToBeReset.connect(proxy.invalidate)

        self._view = view
        self._model = model
        self._proxy = proxy

    def model(self):
        return self._model

    def on_task_selected(self, task_name):
        self._model.set_task(task_name)
        self._proxy.invalidate()

        index = self._view.currentIndex()
        if index.isValid():
            scope = index.data(BaseScopeModel.ScopeRole)
            self.scope_changed.emit(scope)  # for update task
        else:
            scope = self._model.project()
            if scope:  # could be None
                self.scope_changed.emit(scope)

    def on_asset_filtered(self, enabled):
        self._proxy.set_filter_by_task(bool(enabled))
        self._proxy.invalidate()

    def _on_asset_searched(self, text):
        self._proxy.setFilterRegExp(text)

    def _on_selection_changed(self, selected, _):
        indexes = selected.indexes()
        if indexes and indexes[0].isValid():
            index = indexes[0]  # SingleSelection view
            index = self._proxy.mapToSource(index)
            scope = index.data(BaseScopeModel.ScopeRole)
            self.scope_changed.emit(scope)
        else:
            scope = self._model.project()
            if scope:  # could be None
                self.scope_changed.emit(scope)


class ProjectListModel(BaseScopeModel):
    Headers = ["Name"]

    def refresh(self, scopes):
        self.reset()

        for project in scopes:
            item = QtGui.QStandardItem()
            item.setText(project.name)
            item.setData(project, self.ScopeRole)

            if MEMBER_ROLE not in project.roles:
                font = QtGui.QFont()
                font.setItalic(True)
                item.setFont(font)

            self.appendRow(item)


class AssetTreeModel(BaseScopeModel):
    Headers = ["Name"]

    def __init__(self, *args, **kwargs):
        super(AssetTreeModel, self).__init__(*args, **kwargs)
        self._project = None    # type: Project or None
        self._task = None       # type: str or None

    def project(self):
        return self._project

    def task(self):
        return self._task

    def set_task(self, name):
        self._task = name

    def reset(self):
        super(AssetTreeModel, self).reset()
        self._project = None
        self._task = None

    def refresh(self, scopes):
        self.reset()

        _asset_items = dict()
        asset = None
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

        self._project = asset.upstream if asset else None

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


class AssetTreeProxyModel(BaseProxyModel):

    def __init__(self, *args, **kwargs):
        super(AssetTreeProxyModel, self).__init__(*args, **kwargs)
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
