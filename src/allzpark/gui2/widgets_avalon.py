
from typing import List
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets
from .common import SlidePageWidget
from ..backend_avalon import Entrance, Project, Asset
from ..util import singledispatchmethod


class AvalonWidget(QtWidgets.QWidget):
    icon_path = None

    def __init__(self, *args, **kwargs):
        super(AvalonWidget, self).__init__(*args, **kwargs)

        project_list = ProjectListWidget()
        asset_tree = AssetTreeWidget()

        slider = SlidePageWidget()
        slider.addWidget(project_list)
        slider.addWidget(asset_tree)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(slider)

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
        raise NotImplementedError(f"Unknown scope {scope}")

    @enter_workspace.register
    def _(self, scope: Entrance):
        self._list.reset_list(scope.iter_children())
        self.set_page(0)

    @enter_workspace.register
    def _(self, scope: Project):
        pass

    @enter_workspace.register
    def _(self, scope: Asset):
        pass


class ProjectListWidget(QtWidgets.QWidget):
    ItemDataRole = QtCore.Qt.UserRole + 10

    def __init__(self, *args, **kwargs):
        super(ProjectListWidget, self).__init__(*args, **kwargs)

        search_bar = QtWidgets.QLineEdit()
        search_bar.setPlaceholderText("search projects..")

        project_list = QtWidgets.QListWidget()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(search_bar)
        layout.addWidget(project_list)

        self._list = project_list

    def reset_list(self, projects):
        import time
        self._list.clear()

        for project in projects:
            if project.is_active:  # todo: this should be toggleable
                item = QtWidgets.QListWidgetItem()
                item.setText(project.name)
                item.setData(self.ItemDataRole, project)

                self._list.addItem(item)
                time.sleep(0.01)


class AssetTreeWidget(QtWidgets.QWidget):

    def __init__(self, *args, **kwargs):
        super(AssetTreeWidget, self).__init__(*args, **kwargs)

        search_bar = QtWidgets.QLineEdit()
        search_bar.setPlaceholderText("search assets..")

        model = QtGui.QStandardItemModel()
        proxy = QtCore.QSortFilterProxyModel()
        proxy.setSourceModel(model)
        view = QtWidgets.QTreeView()
        view.setModel(proxy)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(search_bar)
        layout.addWidget(view)

        self._view = view
        self._model = model
        self._proxy = proxy


if __name__ == "__main__":
    import os
    from allzpark.backend_avalon import Project, get_entrance
    from Qt5 import QtGui, QtWidgets

    _entrance = get_entrance(uri=os.environ["AVALON_MONGO"])

    app = QtWidgets.QApplication()  # must be inited before all other widgets
    dialog = QtWidgets.QDialog()
    combo = QtWidgets.QComboBox()
    model = QtGui.QStandardItemModel()
    view = QtWidgets.QTreeView()
    view.setModel(model)

    # setup model
    for project_ in _entrance.iter_children():
        if project_.is_active:
            combo.addItem(project_.name, project_)

    # layout
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(combo)
    layout.addWidget(view)

    # signal
    def update_assets(index):
        project_item = combo.itemData(index)  # type: Project
        model.clear()
        _asset_items = dict()
        for asset in project_item.iter_children():
            if not asset.is_hidden:
                item = QtGui.QStandardItem(asset.name)
                _asset_items[asset.name] = item
                if asset.is_silo:
                    model.appendRow(item)
                else:
                    parent = _asset_items[asset.parent.name]
                    parent.appendRow(item)

    combo.currentIndexChanged.connect(update_assets)

    # run
    dialog.open()
    app.exec_()
