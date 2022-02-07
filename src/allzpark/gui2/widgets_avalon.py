
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets
from .common import SlidePageWidget, WorkspaceBase, BaseScopeModel
from ..backend_avalon import Entrance, Project, Asset, Task, MEMBER_ROLE
from ..util import singledispatchmethod, elide


class AvalonWidget(WorkspaceBase):
    icon_path = ":/icons/avalon.svg"

    def __init__(self, *args, **kwargs):
        super(AvalonWidget, self).__init__(*args, **kwargs)

        project_list = ProjectListWidget()
        asset_tree = AssetTreeWidget()

        asset_page = QtWidgets.QWidget()
        tasks = QtWidgets.QComboBox()
        only_tasked = QtWidgets.QCheckBox("Only Tasked Assets")

        layout = QtWidgets.QVBoxLayout(asset_page)
        layout.addWidget(tasks)
        layout.addWidget(only_tasked)
        layout.addWidget(asset_tree)

        slider = SlidePageWidget()
        slider.addWidget(project_list)
        slider.addWidget(asset_page)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(slider)

        project_list.scope_selected.connect(self.workspace_changed.emit)
        asset_tree.scope_selected.connect(self.workspace_changed.emit)
        tasks.currentTextChanged.connect(asset_tree.on_task_selected)
        only_tasked.stateChanged.connect(asset_tree.on_asset_filtered)

        self._projects = project_list
        self._assets = asset_tree
        self._tasks = tasks
        self._slider = slider
        self._page = 0

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
        _ = scope
        self.set_page(0)

    @enter_workspace.register
    def _(self, scope: Project):
        _ = scope
        self.set_page(1)
        self._tasks.clear()
        self._tasks.addItems(sorted(scope.tasks))

    @enter_workspace.register
    def _(self, scope: Asset):
        pass

    @enter_workspace.register
    def _(self, scope: Task):
        pass

    @singledispatchmethod
    def update_workspace(self, scope, scopes):
        raise NotImplementedError(f"Unknown scope {elide(scope)!r}")

    @update_workspace.register
    def _(self, scope: Entrance, scopes: list):
        _ = scope
        return self._projects.model().refresh(scopes)

    @update_workspace.register
    def _(self, scope: Project, scopes: list):
        _ = scope
        return self._assets.model().refresh(scopes)

    @update_workspace.register
    def _(self, scope: Asset, scopes: list):
        _ = scope
        current_task = self._tasks.currentText()
        matched = next((s for s in scopes if s.name == current_task), None)
        if matched:
            self.workspace_changed.emit(matched)
        else:
            pass  # todo: should prompt warning

    @update_workspace.register
    def _(self, scope: Task, scopes: list):
        pass


class ProjectListWidget(QtWidgets.QWidget):
    scope_selected = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super(ProjectListWidget, self).__init__(*args, **kwargs)

        search_bar = QtWidgets.QLineEdit()
        search_bar.setPlaceholderText("search projects..")

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
    scope_selected = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super(AssetTreeWidget, self).__init__(*args, **kwargs)

        search_bar = QtWidgets.QLineEdit()
        search_bar.setPlaceholderText("search assets..")

        model = AssetTreeModel()
        proxy = QtCore.QSortFilterProxyModel()
        proxy.setSourceModel(model)
        proxy.setRecursiveFilteringEnabled(True)
        proxy.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        proxy.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)
        view = QtWidgets.QTreeView()
        view.setModel(proxy)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(search_bar)
        layout.addWidget(view)

        model.modelAboutToBeReset.connect(proxy.invalidate)
        view.clicked.connect(self._on_item_clicked)
        search_bar.textChanged.connect(self._on_asset_searched)

        self._view = view
        self._model = model
        self._proxy = proxy

    def model(self):
        return self._model

    def on_task_selected(self, task_name):
        self._model.set_task(task_name)
        self._proxy.invalidate()
        # todo: after asset filtered by the task, change current scope
        #   if asset selection changed.

    def on_asset_filtered(self, enabled):
        pass

    def _on_asset_searched(self, text):
        self._proxy.setFilterRegExp(text)

    def _on_item_clicked(self, index):
        index = self._proxy.mapToSource(index)
        scope = index.data(BaseScopeModel.ScopeRole)
        self.scope_selected.emit(scope)


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
            if scope.tasks and self._task not in scope.tasks:
                font = QtGui.QFont()
                font.setItalic(True)
                return font

        return super(AssetTreeModel, self).data(index, role)
