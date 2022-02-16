
from ._vendor.Qt5 import QtCore, QtWidgets
from . import widgets


class ProductionPage(widgets.BusyWidget):

    def __init__(self, *args, **kwargs):
        super(ProductionPage, self).__init__(*args, **kwargs)
        self.setObjectName("ProductionPage")

        # top
        head = QtWidgets.QWidget()
        head.setObjectName("ButtonBelt")
        clear_cache = widgets.ClearCacheWidget()
        work_dir = widgets.WorkDirWidget()
        # body
        body = QtWidgets.QWidget()
        # - left side tab #1
        workspace_view = widgets.WorkspaceWidget()
        tools_view = widgets.ToolsView()
        # - left side tab #2
        work_history = widgets.WorkHistoryWidget()
        # - right side
        tool_context = widgets.ToolContextWidget()

        work_split = QtWidgets.QSplitter()
        work_split.addWidget(workspace_view)
        work_split.addWidget(tools_view)

        work_split.setOrientation(QtCore.Qt.Horizontal)
        work_split.setChildrenCollapsible(False)
        work_split.setContentsMargins(0, 0, 0, 0)
        work_split.setStretchFactor(0, 50)
        work_split.setStretchFactor(1, 50)

        tabs = QtWidgets.QTabBar()
        stack = QtWidgets.QStackedWidget()
        stack.setObjectName("TabStackWidgetLeft")
        tabs.setShape(tabs.RoundedWest)
        tabs.setDocumentMode(True)
        # QTabWidget's frame (pane border) will not be rendered if documentMode
        # is enabled, so we make our own with bar + stack with border.
        tabs.addTab("Workspaces")
        stack.addWidget(work_split)
        tabs.addTab("History")
        stack.addWidget(work_history)

        body_split = QtWidgets.QSplitter()
        body_split.addWidget(body)
        body_split.addWidget(tool_context)

        body_split.setOrientation(QtCore.Qt.Horizontal)
        body_split.setChildrenCollapsible(False)
        body_split.setContentsMargins(0, 0, 0, 0)
        body_split.setStretchFactor(0, 70)
        body_split.setStretchFactor(1, 30)

        layout = QtWidgets.QHBoxLayout(head)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(clear_cache)
        layout.addWidget(work_dir, stretch=True)

        layout = QtWidgets.QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(tabs, alignment=QtCore.Qt.AlignTop)
        layout.addWidget(stack, stretch=True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(head)
        layout.addWidget(body_split, stretch=True)

        tabs.currentChanged.connect(stack.setCurrentIndex)
