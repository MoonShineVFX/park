
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
        task_list = TaskListWidget()

        slider = SlidePageWidget()
        slider.addWidget(project_list)
        slider.addWidget(asset_tree)
        slider.addWidget(task_list)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(slider)

        project_list.scope_selected.connect(self.workspace_changed.emit)
        asset_tree.scope_selected.connect(self.workspace_changed.emit)
        task_list.scope_selected.connect(self.workspace_changed.emit)

        self._slider = slider
        self._list = project_list
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

    @enter_workspace.register
    def _(self, scope: Asset):
        _ = scope
        self.set_page(2)

    @enter_workspace.register
    def _(self, scope: Task):
        pass

    @singledispatchmethod
    def get_model(self, scope):
        raise NotImplementedError(f"Unknown scope {elide(scope)!r}")

    @get_model.register
    def _(self, scope: Entrance):
        _ = scope
        return self._slider.widget(0).model()

    @get_model.register
    def _(self, scope: Project):
        _ = scope
        return self._slider.widget(1).model()

    @get_model.register
    def _(self, scope: Asset):
        _ = scope
        return self._slider.widget(2).model()

    @get_model.register
    def _(self, scope: Task):
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
        view = QtWidgets.QTreeView()
        view.setModel(proxy)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(search_bar)
        layout.addWidget(view)

        model.modelAboutToBeReset.connect(proxy.invalidate)
        view.clicked.connect(self._on_item_clicked)

        self._view = view
        self._model = model
        self._proxy = proxy

    def model(self):
        return self._model

    def _on_item_clicked(self, index):
        index = self._proxy.mapToSource(index)
        scope = index.data(BaseScopeModel.ScopeRole)
        self.scope_selected.emit(scope)


class TaskListWidget(QtWidgets.QWidget):
    scope_selected = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super(TaskListWidget, self).__init__(*args, **kwargs)

        model = TaskListModel()
        view = QtWidgets.QListView()
        view.setModel(model)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(view)

        view.clicked.connect(self._on_item_clicked)

        self._view = view
        self._model = model

    def model(self):
        return self._model

    def _on_item_clicked(self, index):
        scope = index.data(BaseScopeModel.ScopeRole)
        self.scope_selected.emit(scope)


class ProjectListModel(BaseScopeModel):
    Headers = ["Name"]

    def refresh(self, scope):
        self.beginResetModel()
        self.clear()

        for project in scope.iter_children():
            # todo: this should be toggleable
            if project.is_active and MEMBER_ROLE in project.roles:
                item = QtGui.QStandardItem()
                item.setText(project.name)
                item.setData(project, self.ScopeRole)

                self.appendRow(item)

        self.endResetModel()


class AssetTreeModel(BaseScopeModel):
    Headers = ["Name"]

    def refresh(self, scope):
        self.beginResetModel()
        self.clear()

        _asset_items = dict()
        for asset in scope.iter_children():
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

        self.endResetModel()


class TaskListModel(BaseScopeModel):
    Headers = ["Name"]

    def refresh(self, scope):
        self.beginResetModel()
        self.clear()

        for task in scope.iter_children():
            item = QtGui.QStandardItem()
            item.setText(task.name)
            item.setData(task, self.ScopeRole)

            self.appendRow(item)

        self.endResetModel()
