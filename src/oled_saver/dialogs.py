"""Qt dialogs for OLED Saver."""

from PyQt6.QtCore import QTime, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
)


class MonitorSelectDialog(QDialog):
    """Dialog to select which monitor(s) to target for idle actions."""

    def __init__(self, monitors, preselected=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OLED Saver — Select Monitors")
        self.selected_connectors = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select monitors for blank/dim:"))

        self.list_widget = QListWidget()
        for connector, model in monitors:
            item = QListWidgetItem(f"{connector}  —  {model}")
            item.setData(Qt.ItemDataRole.UserRole, connector)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if preselected and connector in preselected:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        self.selected_connectors = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                self.selected_connectors.append(item.data(Qt.ItemDataRole.UserRole))
        if self.selected_connectors:
            self.accept()


class NightSettingsDialog(QDialog):
    """Dialog to configure night mode settings."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Night Mode Settings")
        self.config = config

        layout = QFormLayout(self)

        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("HH:mm")
        self.start_edit.setTime(QTime.fromString(config.night_mode_start, "HH:mm"))
        layout.addRow("Start time:", self.start_edit)

        self.end_edit = QTimeEdit()
        self.end_edit.setDisplayFormat("HH:mm")
        self.end_edit.setTime(QTime.fromString(config.night_mode_end, "HH:mm"))
        layout.addRow("End time:", self.end_edit)

        self.brightness_spin = QSpinBox()
        self.brightness_spin.setRange(5, 100)
        self.brightness_spin.setSuffix("%")
        self.brightness_spin.setValue(config.night_mode_brightness)
        layout.addRow("Brightness:", self.brightness_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self):
        return (
            self.start_edit.time().toString("HH:mm"),
            self.end_edit.time().toString("HH:mm"),
            self.brightness_spin.value(),
        )
