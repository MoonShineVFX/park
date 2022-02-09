
from ._vendor.Qt5 import QtCore, QtWidgets
from . import widgets


class ProductionPage(QtWidgets.QWidget):

    def __init__(self, *args, **kwargs):
        super(ProductionPage, self).__init__(*args, **kwargs)

        body = QtWidgets.QWidget()
        workspace_view = widgets.WorkspaceWidget()
        tools_view = widgets.ToolsView()
        workspace = QtWidgets.QWidget()
        work_history = widgets.WorkHistoryWidget()

        tool_scope = widgets.ToolScopeWidget()
        tool_context = widgets.ToolContextWidget()

        tabs = QtWidgets.QTabBar()
        stack = QtWidgets.QStackedWidget()
        stack.setObjectName("TabStackWidgetLeft")
        tabs.setShape(tabs.RoundedWest)
        tabs.setDocumentMode(True)
        # QTabWidget's frame (pane border) will not be rendered if documentMode
        # is enabled, so we make our own with bar + stack with border.
        tabs.addTab("Workspaces")
        stack.addWidget(workspace)
        tabs.addTab("History")
        stack.addWidget(work_history)

        tool_split = QtWidgets.QSplitter()
        tool_split.addWidget(tool_scope)
        tool_split.addWidget(tool_context)

        body_split = QtWidgets.QSplitter()
        body_split.addWidget(body)
        body_split.addWidget(tool_split)

        tool_split.setOrientation(QtCore.Qt.Vertical)
        tool_split.setChildrenCollapsible(False)
        tool_split.setContentsMargins(0, 0, 0, 0)
        tool_split.setStretchFactor(0, 35)
        tool_split.setStretchFactor(1, 65)

        body_split.setOrientation(QtCore.Qt.Horizontal)
        body_split.setChildrenCollapsible(False)
        body_split.setContentsMargins(0, 0, 0, 0)
        body_split.setStretchFactor(0, 50)
        body_split.setStretchFactor(1, 50)

        layout = QtWidgets.QHBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(workspace_view)
        layout.addWidget(tools_view)

        layout = QtWidgets.QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(tabs, alignment=QtCore.Qt.AlignTop)
        layout.addWidget(stack, stretch=True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(body_split)

        tabs.currentChanged.connect(stack.setCurrentIndex)
