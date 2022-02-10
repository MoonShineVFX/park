
import logging
from typing import List, Union
from ._vendor.Qt5 import QtCore, QtGui, QtWidgets
from ..backend_sg_sync import Entrance, Project
from ..util import elide
from ..core import AbstractScope
from .models import BaseScopeModel, BaseProxyModel

log = logging.getLogger("allzpark")


class ShotGridSyncWidget(QtWidgets.QWidget):
    icon_path = ":/icons/sg_logo.png"
    tools_requested = QtCore.Signal(AbstractScope)
    workspace_changed = QtCore.Signal(AbstractScope)

    def __init__(self, *args, **kwargs):
        super(ShotGridSyncWidget, self).__init__(*args, **kwargs)

        project_list = ProjectListWidget()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(project_list)

        project_list.scope_selected.connect(self.workspace_changed.emit)

        self._entrance = None  # type: Entrance or None
        self._projects = project_list

    def enter_workspace(self, scope: Union[Entrance, Project]) -> None:
        if isinstance(scope, Entrance):
            self._entrance = scope

        elif isinstance(scope, Project):
            self.tools_requested.emit(scope)

        else:
            pass

    def update_workspace(self, scopes: List[Project]) -> None:
        if not scopes:
            log.debug("No scopes to update.")
            return
        upstream = scopes[0].upstream  # take first scope as sample

        if isinstance(upstream, Entrance):
            self._projects.model().refresh(scopes)
        else:
            raise NotImplementedError(f"Invalid upstream {elide(upstream)!r}")


class ProjectListWidget(QtWidgets.QWidget):
    scope_selected = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super(ProjectListWidget, self).__init__(*args, **kwargs)
        self.setObjectName("ShotGridProjectView")

        search_bar = QtWidgets.QLineEdit()
        search_bar.setPlaceholderText("search projects..")

        # todo: toggle tank_name <-> name

        model = ProjectListModel()
        proxy = BaseProxyModel()
        proxy.setSourceModel(model)
        view = QtWidgets.QListView()
        view.setModel(proxy)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(search_bar)
        layout.addWidget(view)

        view.clicked.connect(self._on_item_clicked)
        search_bar.textChanged.connect(self._on_project_searched)

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


class ProjectListModel(BaseScopeModel):
    Headers = ["Name"]

    def refresh(self, scopes):
        self.reset()

        for project in scopes:
            item = QtGui.QStandardItem()
            item.setText(project.name)
            item.setData(project, self.ScopeRole)

            self.appendRow(item)
