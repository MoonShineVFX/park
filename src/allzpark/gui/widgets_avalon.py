
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
        layout.addWidget(current_project, stretch=True)

        layout = QtWidgets.QHBoxLayout(task_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(only_tasked)
        layout.addWidget(tasks, stretch=True)

        layout = QtWidgets.QVBoxLayout(asset_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(top_bar)
        layout.addWidget(task_bar)
        layout.addSpacing(10)
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
        asset_tree.scope_changed.connect(self._on_asset_changed)
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
        scope.joined = True if bool(joined) else None
        log.debug(f"Refresh workspace (filtering projects): {scope}")
        self._workspace_refreshed(scope, cache_clear=True)

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
    filter_toggled = QtCore.Signal(bool)
    scope_selected = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super(ProjectListWidget, self).__init__(*args, **kwargs)
        self.setObjectName("AvalonProjectView")

        top_bar = QtWidgets.QWidget()
        top_bar.setObjectName("ButtonBelt")
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
        view = QtWidgets.QTreeView()
        view.setModel(proxy)
        view.setIndentation(2)
        view.setHeaderHidden(True)

        layout = QtWidgets.QHBoxLayout(top_bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(search_bar, stretch=True)
        layout.addWidget(filter_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(top_bar)
        layout.addWidget(view)

        search_bar.textChanged.connect(self._on_project_searched)
        filter_btn.toggled.connect(self._on_filter_toggled)
        view.clicked.connect(self._on_item_clicked)
        model.modelReset.connect(self._on_model_resetted)

        self._view = view
        self._proxy = proxy
        self._model = model
        self.__member_changed = None

    def model(self):
        return self._model

    def _on_filter_toggled(self, state):
        self.filter_toggled.emit(state)
        self._model.set_filtered(state)

    def _on_item_clicked(self, index):
        toggled = index.data(ProjectListModel.ToggledRole)
        if toggled:  # user is toggling, not clicking it.
            self._on_item_toggled(self._proxy.mapToSource(index))
            return

        scope = index.data(ProjectListModel.ScopeRole)
        self.scope_selected.emit(scope)

    def _on_project_searched(self, text):
        self._proxy.setFilterRegExp(text)

    def _on_item_toggled(self, index):
        model_ = index.model()
        project = model_.data(index, self._model.ScopeRole)  # type: Project
        join = bool(index.data(QtCore.Qt.CheckStateRole))
        if join:
            log.debug(f"Joining project {project.name}")
            result = project.db.join_project(project.coll)
        else:
            log.debug(f"Leaving project {project.name}")
            result = project.db.leave_project(project.coll)

        if result.modified_count:
            log.debug("Project membership status updated.")
            self.__member_changed = project.name
        else:
            log.warning("Project membership status not changed.")

        # reset
        self._model.setData(index, False, ProjectListModel.ToggledRole)

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
    scope_changed = QtCore.Signal(AbstractScope)

    def __init__(self, *args, **kwargs):
        super(AssetTreeWidget, self).__init__(*args, **kwargs)
        self.setObjectName("AvalonAssetView")

        top_bar = QtWidgets.QWidget()
        top_bar.setObjectName("ButtonBelt")
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
        layout.addWidget(search_bar, stretch=True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(top_bar)
        layout.addWidget(view)

        selection.selectionChanged.connect(self._on_selection_changed)
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
        else:
            self._view.update()

        indexes = self._view.selectionModel().selectedIndexes()
        if indexes and indexes[0].isValid():
            index = indexes[0]  # SingleSelection view
            scope = index.data(BaseScopeModel.ScopeRole)
            self.scope_changed.emit(scope)  # for update task
        else:
            scope = self._model.project()
            if scope:  # could be None
                self.scope_changed.emit(scope)

    def on_asset_filtered(self, enabled):
        self._model.set_task_filtering(bool(enabled))
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

    def changeEvent(self, event):
        super(AssetTreeWidget, self).changeEvent(event)
        if event.type() == QtCore.QEvent.StyleChange:
            # update color when theme changed
            self._update_placeholder_color()

    def _update_placeholder_color(self):
        color = self.palette().color(QtGui.QPalette.PlaceholderText)
        self._model.set_placeholder_color(color)


class ProjectListModel(BaseScopeModel):
    ToggledRole = QtCore.Qt.UserRole + 20
    Headers = ["Name"]

    def __init__(self, *args, **kwargs):
        super(ProjectListModel, self).__init__(*args, **kwargs)
        self._filtered = True  # default filtered (only joined projects)

    def set_filtered(self, state):
        self._filtered = bool(state)

    def refresh(self, scopes):
        self.beginResetModel()
        self.reset()

        for project in scopes:
            item = QtGui.QStandardItem()
            item.setIcon(QtGui.QIcon(":/icons/_.svg"))  # placeholder icon
            item.setText(project.name)
            item.setData(project, self.ScopeRole)
            item.setData(False, self.ToggledRole)

            if MEMBER_ROLE not in project.roles:
                font = QtGui.QFont()
                font.setItalic(True)
                item.setFont(font)
                item.setData(QtCore.Qt.Unchecked, QtCore.Qt.CheckStateRole)
            else:
                item.setData(QtCore.Qt.Checked, QtCore.Qt.CheckStateRole)

            self.appendRow(item)

        self.endResetModel()

    def data(self, index, role=QtCore.Qt.DisplayRole):
        """
        :param QtCore.QModelIndex index:
        :param int role:
        :rtype: Any
        """
        if not index.isValid():
            return

        if role == QtCore.Qt.CheckStateRole:
            if not self._filtered:
                item = self.itemFromIndex(index)
                return item.data(QtCore.Qt.CheckStateRole)
            else:
                return

        return super(ProjectListModel, self).data(index, role)

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        """

        :param index:
        :param value:
        :param role:
        :type index: QtCore.QModelIndex
        :type value: Any
        :type role: int
        :return:
        :rtype: bool
        """
        if not index.isValid():
            return False

        if role == QtCore.Qt.CheckStateRole:
            item = self.itemFromIndex(index)
            item.setData(value, QtCore.Qt.CheckStateRole)
            item.setData(True, self.ToggledRole)
            return True

        if role == self.ToggledRole:
            item = self.itemFromIndex(index)
            item.setData(False, self.ToggledRole)
            return True

        return super(ProjectListModel, self).setData(index, value, role)

    def flags(self, index):
        """
        :param QtCore.QModelIndex index:
        :rtype: QtCore.Qt.ItemFlags
        """
        if not index.isValid():
            return

        base_flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        if not self._filtered:
            return base_flags | QtCore.Qt.ItemIsUserCheckable
        return base_flags


class AssetTreeModel(BaseScopeModel):
    TaskFilterRole = QtCore.Qt.UserRole + 20
    Headers = ["Name"]

    def __init__(self, *args, **kwargs):
        super(AssetTreeModel, self).__init__(*args, **kwargs)
        self._project = None    # type: Project or None
        self._task = None       # type: str or None
        self._icon_silo = QtGui.QIcon(":/icons/collection.svg")
        self._icon_tasked = QtGui.QIcon(":/icons/folder.svg")
        self._icon_tasked_not = QtGui.QIcon(":/icons/folder-x.svg")
        self._icon_tasked_semi = QtGui.QIcon(":/icons/folder-minus.svg")
        self._task_filtering = None
        self._placeholder_color = None

    def set_placeholder_color(self, color):
        self._placeholder_color = color

    def set_task_filtering(self, enabled):
        self._task_filtering = enabled

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

        if role == QtCore.Qt.ForegroundRole:
            scope = index.data(self.ScopeRole)  # type: Asset
            if scope.is_leaf and not is_asset_tasked(scope, self._task):
                return self._placeholder_color

        if role == QtCore.Qt.DecorationRole:
            scope = index.data(self.ScopeRole)  # type: Asset
            if scope.is_silo:
                return self._icon_silo
            elif self._task_filtering or is_asset_tasked(scope, self._task):
                return self._icon_tasked
            elif not scope.is_leaf and self._task in scope.child_task:
                return self._icon_tasked_semi
            else:
                return self._icon_tasked_not

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


# todo: lru-cache this
def is_asset_tasked(scope: Asset, task_name: str) -> bool:
    if ASSET_MUST_BE_TASKED:
        return task_name in scope.tasks
    return not scope.tasks or task_name in scope.tasks
