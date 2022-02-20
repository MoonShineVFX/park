
import logging
from typing import List, Union
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets
from ..backend_avalon import Entrance, Project, Asset, Task, MEMBER_ROLE
from ..util import elide
from ..core import AbstractScope
from .widgets import SlidePageWidget, ScopeLineLabel, ComboBox
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
    workspace_refreshed = QtCore.Signal(AbstractScope, bool)

    def __init__(self, *args, **kwargs):
        super(AvalonWidget, self).__init__(*args, **kwargs)

        label = QtWidgets.QLabel("Avalon")
        label.setObjectName("BackendLabel")

        project_list = ProjectListWidget()
        asset_tree = AssetTreeWidget()

        asset_page = QtWidgets.QWidget()

        top_bar = QtWidgets.QWidget()
        top_bar.setObjectName("ButtonBelt")
        home = QtWidgets.QPushButton()
        home.setObjectName("AvalonHomeButton")
        slash = QtWidgets.QLabel()
        slash.setObjectName("AvalonHomeSlash")
        current_project = ScopeLineLabel("current project..")

        task_bar = QtWidgets.QWidget()
        task_bar.setObjectName("ButtonBelt")
        only_tasked = QtWidgets.QPushButton()
        only_tasked.setObjectName("AvalonTaskFilter")
        only_tasked.setCheckable(True)
        only_tasked.setChecked(False)
        tasks = ComboBox()

        layout = QtWidgets.QHBoxLayout(top_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(home)
        layout.addWidget(slash)
        layout.addWidget(current_project, stretch=True)

        layout = QtWidgets.QHBoxLayout(task_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(only_tasked)
        layout.addWidget(tasks, stretch=True)

        layout = QtWidgets.QVBoxLayout(asset_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(top_bar)
        layout.addWidget(task_bar)
        layout.addWidget(asset_tree)

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
        asset_tree.refresh_clicked.connect(self._on_asset_refreshed)
        tasks.currentTextChanged.connect(asset_tree.on_task_selected)
        only_tasked.toggled.connect(asset_tree.on_asset_filtered)

        self.__inited = False
        self.__cleared = False
        self._entrance = None  # type: Entrance or None
        self._projects = project_list
        self._assets = asset_tree
        self._tasks = tasks
        self._tasked = only_tasked
        self._slider = slider
        self._page = 0
        self._current_project = current_project
        self._entered_scope = None  # type: AbstractScope or None

    def _workspace_refreshed(self, scope, cache_clear=False):
        self.__cleared = cache_clear
        self.workspace_refreshed.emit(scope, cache_clear)

    def _on_home_clicked(self):
        assert self._entrance is not None
        self.workspace_changed.emit(self._entrance)

    def _on_project_filtered(self, joined):
        scope = self._entrance
        scope.joined = bool(joined)
        log.debug(f"Refresh workspace (filtering projects): {scope}")
        self._workspace_refreshed(scope, cache_clear=True)

    def _on_project_refreshed(self):
        scope = self._entrance
        log.debug(f"Refresh workspace (refresh projects): {scope}")
        self._workspace_refreshed(scope)

    def _on_asset_refreshed(self, scope: Project):
        log.debug(f"Refresh workspace (refresh assets): {scope}")
        self._workspace_refreshed(scope)

    def _on_asset_changed(self, scope: Union[Asset, Project]):
        if self._page != 1:
            return
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
            self._tasks.blockSignals(True)
            self._tasks.clear()
            self._tasks.addItems(scope.tasks)
            self._tasks.blockSignals(False)
        else:
            return

        log.debug(f"Requesting tools for scope: {scope}")
        self.tools_requested.emit(scope)
        log.debug(f"Refresh workspace (enter workspace): {scope}")
        self._workspace_refreshed(scope)
        self._entered_scope = scope

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
            self._tasked.toggled.emit(False)
            # if the task filter is on, model refresh will be slower because
            # the filterAcceptsRow() is also working while adding items into
            # model. so we make sure it's disabled and set it back later.
            self._assets.model().refresh(scopes)
            self._assets.model().set_task(self._tasks.currentText())
            self._tasked.toggled.emit(self._tasked.isChecked())

        elif isinstance(upstream, Asset):
            pass

        elif isinstance(upstream, Task):
            raise NotImplementedError(f"Task {elide(upstream)!r} shouldn't "
                                      f"have downstream scope.")
        else:
            raise NotImplementedError(f"Unknown upstream {elide(upstream)!r}")

    def on_cache_cleared(self):
        if self._entered_scope is None:
            return
        if self.__cleared:  # avoid refreshing workspace twice.
            self.__cleared = False
            return

        scope = self._entered_scope  # type: AbstractScope
        if not scope.exists():
            if scope.upstream is not None:
                # fallback to upstream
                self._entered_scope = scope.upstream
                self.on_cache_cleared()
            else:
                # backend lost
                self._projects.model().reset()
                self.set_page(0)
                return

        log.debug(f"Refresh workspace (cache cleared): {scope}")
        self._workspace_refreshed(scope)


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
        search_bar.setClearButtonEnabled(True)
        filter_btn = QtWidgets.QPushButton()
        filter_btn.setObjectName("AvalonProjectArchive")
        filter_btn.setCheckable(True)
        filter_btn.setChecked(True)  # the default defined in backend module

        model = ProjectListModel()
        proxy = BaseProxyModel()
        proxy.setSourceModel(model)
        view = QtWidgets.QListView()
        view.setModel(proxy)
        view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

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

        search_bar.textChanged.connect(self._on_project_searched)
        filter_btn.toggled.connect(self.filter_toggled)
        refresh_btn.clicked.connect(self.refresh_clicked)
        view.clicked.connect(self._on_item_clicked)
        view.customContextMenuRequested.connect(self._on_right_click)
        model.modelReset.connect(self._on_model_resetted)

        self._view = view
        self._proxy = proxy
        self._model = model
        self.__member_changed = None

    def model(self):
        return self._model

    def _on_item_clicked(self, index):
        scope = index.data(BaseScopeModel.ScopeRole)
        self.scope_selected.emit(scope)

    def _on_project_searched(self, text):
        self._proxy.setFilterRegExp(text)

    def _on_right_click(self, position):
        index = self._view.indexAt(position)

        if not index.isValid():
            # Clicked outside any item
            return

        menu = QtWidgets.QMenu(self._view)
        model_ = index.model()
        project = model_.data(index, self._model.ScopeRole)  # type: Project
        is_member = MEMBER_ROLE in project.roles

        _label = "Leave" if is_member else "Join"
        member_action = QtWidgets.QAction(_label, menu)

        menu.addAction(member_action)

        def on_member():
            if is_member:
                result = project.db.leave_project(project.coll)
            else:
                result = project.db.join_project(project.coll)

            if result.modified_count:
                _index = self._proxy.mapToSource(index)
                self._model.removeRow(_index.row(), _index.parent())
                self.__member_changed = project.name

        member_action.triggered.connect(on_member)

        menu.move(QtGui.QCursor.pos())
        menu.show()

    def _on_model_resetted(self):
        if self.__member_changed:
            items = self._model.findItems(self.__member_changed)
            if items:
                project_item = items[0]
                index = self._proxy.mapFromSource(project_item.index())
                selection = self._view.selectionModel()
                selection.setCurrentIndex(index, selection.ClearAndSelect)
                self._view.scrollTo(index)
                self.__member_changed = None


class AssetTreeWidget(QtWidgets.QWidget):
    refresh_clicked = QtCore.Signal(Project)
    scope_changed = QtCore.Signal(AbstractScope)

    def __init__(self, *args, **kwargs):
        super(AssetTreeWidget, self).__init__(*args, **kwargs)
        self.setObjectName("AvalonAssetView")

        top_bar = QtWidgets.QWidget()
        top_bar.setObjectName("ButtonBelt")
        refresh_btn = QtWidgets.QPushButton()
        refresh_btn.setObjectName("RefreshButton")
        search_bar = QtWidgets.QLineEdit()
        search_bar.setPlaceholderText("search assets..")
        search_bar.setClearButtonEnabled(True)

        model = AssetTreeModel()
        proxy = AssetTreeProxyModel()
        proxy.setSourceModel(model)
        view = QtWidgets.QTreeView()
        view.setSelectionMode(view.SingleSelection)
        view.setHeaderHidden(True)
        view.setModel(proxy)
        selection = view.selectionModel()

        layout = QtWidgets.QHBoxLayout(top_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(refresh_btn)
        layout.addWidget(search_bar, stretch=True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(top_bar)
        layout.addWidget(view)

        selection.selectionChanged.connect(self._on_selection_changed)
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        search_bar.textChanged.connect(self._on_asset_searched)

        self._view = view
        self._model = model
        self._proxy = proxy

    def model(self):
        return self._model

    def on_task_selected(self, task_name):
        self._model.set_task(task_name)

        if self._proxy.is_filter_by_task():
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

    def _on_refresh_clicked(self):
        scope = self._model.project()
        if scope:  # could be None
            self.refresh_clicked.emit(scope)


class ProjectListModel(BaseScopeModel):
    Headers = ["Name"]

    def refresh(self, scopes):
        self.beginResetModel()
        self.reset()

        for project in scopes:
            item = QtGui.QStandardItem()
            item.setIcon(QtGui.QIcon(":/icons/_.svg"))  # placeholder icon
            item.setText(project.name)
            item.setData(project, self.ScopeRole)

            if MEMBER_ROLE not in project.roles:
                font = QtGui.QFont()
                font.setItalic(True)
                item.setFont(font)

            self.appendRow(item)

        self.endResetModel()


class AssetTreeModel(BaseScopeModel):
    TaskFilterRole = QtCore.Qt.UserRole + 20
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

        if role == self.TaskFilterRole:
            scope = index.data(self.ScopeRole)  # type: Asset
            return not scope.is_silo and is_asset_tasked(scope, self._task)

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

    def is_filter_by_task(self):
        return self._filter_by_task

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
            return index.data(AssetTreeModel.TaskFilterRole)

        return accepted


def is_asset_tasked(scope: Asset, task_name: str) -> bool:
    if ASSET_MUST_BE_TASKED:
        return task_name in scope.tasks
    return not scope.tasks or task_name in scope.tasks
