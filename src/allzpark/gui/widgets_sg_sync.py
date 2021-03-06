
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
    workspace_refreshed = QtCore.Signal(AbstractScope, bool)

    def __init__(self, *args, **kwargs):
        super(ShotGridSyncWidget, self).__init__(*args, **kwargs)

        label = QtWidgets.QLabel("ShotGrid Sync")
        label.setObjectName("BackendLabel")

        project_list = ProjectListWidget()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addWidget(project_list)

        project_list.scope_selected.connect(self._on_project_scope_changed)
        project_list.scope_deselected.connect(self._on_project_scope_changed)

        self.__inited = False
        self._entrance = None  # type: Entrance or None
        self._projects = project_list
        self._entered_scope = None

    def _on_project_scope_changed(self, scope=None):
        if scope is None and self._entrance is None:
            return
        scope = scope or self._entrance
        self.workspace_changed.emit(scope)

    def _workspace_refreshed(self, scope, cache_clear=False):
        self.workspace_refreshed.emit(scope, cache_clear)

    def enter_workspace(self,
                        scope: Union[Entrance, Project],
                        backend_changed: bool) -> None:
        if isinstance(scope, Entrance):
            self._entrance = scope
            if backend_changed and self.__inited:
                return  # shotgrid slow, only auto update on start

        elif isinstance(scope, Project):
            pass

        else:
            return

        self.tools_requested.emit(scope)
        self._workspace_refreshed(scope)
        self._entered_scope = scope

    def update_workspace(self, scopes: List[Project]) -> None:
        if not scopes:
            log.debug("No scopes to update.")
            return
        upstream = scopes[0].upstream  # take first scope as sample

        if isinstance(upstream, Entrance):
            self._projects.model().refresh(scopes)
            self.__inited = True
        else:
            raise NotImplementedError(f"Invalid upstream {elide(upstream)!r}")

    def on_cache_cleared(self):
        if self._entered_scope is not None:
            self._workspace_refreshed(self._entered_scope)


class ProjectListWidget(QtWidgets.QWidget):
    scope_selected = QtCore.Signal(AbstractScope)
    scope_deselected = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super(ProjectListWidget, self).__init__(*args, **kwargs)
        self.setObjectName("ShotGridProjectView")

        search_bar = QtWidgets.QLineEdit()
        search_bar.setPlaceholderText("search projects..")
        search_bar.setClearButtonEnabled(True)

        # todo: toggle tank_name <-> name

        model = ProjectListModel()
        proxy = BaseProxyModel()
        proxy.setSourceModel(model)
        view = QtWidgets.QListView()
        view.setModel(proxy)
        selection = view.selectionModel()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(search_bar)
        layout.addWidget(view)

        search_bar.textChanged.connect(self._on_project_searched)
        selection.selectionChanged.connect(self._on_selection_changed)

        self._view = view
        self._proxy = proxy
        self._model = model

    def model(self):
        return self._model

    def _on_project_searched(self, text):
        self._proxy.setFilterRegExp(text)

    def _on_selection_changed(self, selected, _):
        indexes = selected.indexes()
        if indexes and indexes[0].isValid():
            index = indexes[0]  # SingleSelection view
            index = self._proxy.mapToSource(index)
            scope = index.data(BaseScopeModel.ScopeRole)
            self.scope_selected.emit(scope)
        else:
            self.scope_deselected.emit()


class ProjectListModel(BaseScopeModel):
    Headers = ["Name"]

    def refresh(self, scopes):
        self.reset()

        for project in sorted(scopes, key=lambda s: s.name):
            item = QtGui.QStandardItem()
            item.setText(project.name)
            item.setData(project, self.ScopeRole)

            self.appendRow(item)
