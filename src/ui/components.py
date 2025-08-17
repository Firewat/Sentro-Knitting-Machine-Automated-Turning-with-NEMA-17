#!/usr/bin/env python3
"""
Custom UI Components
Optimized, reusable UI widgets
"""

from PyQt6.QtWidgets import (
    QSpinBox, QComboBox, QTableWidget, QTableWidgetItem, 
    QHeaderView, QProgressBar, QDialog, QVBoxLayout, 
    QHBoxLayout, QLabel, QPushButton, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from typing import List, Optional, Callable


class NoWheelSpinBox(QSpinBox):
    """SpinBox that ignores wheel events to prevent accidental changes"""
    
    def wheelEvent(self, event):
        """Ignore wheel events"""
        event.ignore()


class NoWheelComboBox(QComboBox):
    """ComboBox that ignores wheel events to prevent accidental changes"""
    
    def wheelEvent(self, event):
        """Ignore wheel events"""
        event.ignore()


class OptimizedTableWidget(QTableWidget):
    """Optimized table widget for pattern visualization"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_table()
    
    def _setup_table(self):
        """Setup table with optimized settings"""
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.setShowGrid(True)
        
        # Optimize performance
        self.setUpdatesEnabled(False)
        
        # Setup headers
        self.verticalHeader().setVisible(True)
        self.horizontalHeader().setVisible(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setDefaultSectionSize(60)
        
        # Apply Excel-like styling
        self.setStyleSheet("""
            QTableWidget {
                gridline-color: #d0d0d0;
                background-color: white;
                alternate-background-color: #f8f8f8;
                selection-background-color: transparent;
                border: 1px solid #d0d0d0;
            }
            QTableWidget::item {
                padding: 4px;
                text-align: center;
                border: none;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #e0e0e0;
                font-weight: bold;
                padding: 4px;
                border: 1px solid #b0b0b0;
                font-size: 10px;
            }
        """)
    
    def clear_efficiently(self):
        """Clear table content efficiently"""
        self.setUpdatesEnabled(False)
        self.clear()
        self.setRowCount(0)
        self.setColumnCount(0)
    
    def populate_grid(self, rows: int, columns: int, data_callback: Callable[[int, int], tuple]):
        """Populate grid efficiently with callback for cell data
        
        Args:
            rows: Number of rows
            columns: Number of columns  
            data_callback: Function(row, col) -> (text, background_color, text_color)
        """
        self.setUpdatesEnabled(False)
        try:
            self.setRowCount(rows)
            self.setColumnCount(columns)
            
            # Set headers
            col_headers = [f"N{i+1}" for i in range(columns)]
            self.setHorizontalHeaderLabels(col_headers)
            
            # Populate cells
            for row in range(rows):
                for col in range(columns):
                    text, bg_color, text_color = data_callback(row, col)
                    
                    item = QTableWidgetItem(str(text))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    
                    if bg_color:
                        item.setBackground(QColor(bg_color))
                    if text_color:
                        item.setForeground(QColor(text_color))
                    
                    self.setItem(row, col, item)
                
                # Update row header
                self.setVerticalHeaderItem(row, QTableWidgetItem(f"R{row+1}"))
        
        finally:
            self.setUpdatesEnabled(True)
            self.update()


class ProgressDialog(QDialog):
    """Modern progress dialog with cancellation support"""
    
    cancelled = pyqtSignal()
    
    def __init__(self, title: str, parent=None, cancellable: bool = True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(400, 120)
        self._cancelled = False
        self._setup_ui(cancellable)
    
    def _setup_ui(self, cancellable: bool):
        """Setup dialog UI"""
        layout = QVBoxLayout(self)
        
        # Status label
        self.status_label = QLabel("Preparing...")
        layout.addWidget(self.status_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        layout.addWidget(self.progress_bar)
        
        # Details label
        self.details_label = QLabel("")
        self.details_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self.details_label)
        
        # Buttons
        if cancellable:
            button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
            button_box.clicked.connect(self._on_cancel)
            layout.addWidget(button_box)
    
    def update_progress(self, current: int, total: int, status: str = "", details: str = ""):
        """Update progress display"""
        if total > 0:
            percentage = int((current / total) * 100)
            self.progress_bar.setValue(percentage)
        
        if status:
            self.status_label.setText(status)
        
        if details:
            self.details_label.setText(details)
        
        # Process events to keep UI responsive
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
    
    def _on_cancel(self):
        """Handle cancellation"""
        self._cancelled = True
        self.cancelled.emit()
        self.reject()
    
    @property
    def is_cancelled(self) -> bool:
        """Check if operation was cancelled"""
        return self._cancelled


class ThemeManager:
    """Manages application themes and styling"""
    
    @staticmethod
    def apply_theme(app, theme_name: str, theme_config: dict):
        """Apply theme to application"""
        style = f"""
        QMainWindow {{
            background-color: {theme_config['background']};
            color: {theme_config['text']};
        }}
        
        QTabWidget::pane {{
            border: 1px solid {theme_config['secondary']};
            background-color: {theme_config['background']};
        }}
        
        QTabWidget::tab-bar {{
            alignment: left;
        }}
        
        QTabBar::tab {{
            background-color: {theme_config['primary']};
            color: {theme_config['text']};
            padding: 8px 12px;
            margin-right: 2px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }}
        
        QTabBar::tab:selected {{
            background-color: {theme_config['background']};
            border-bottom: 2px solid {theme_config['accent']};
        }}
        
        QTabBar::tab:hover {{
            background-color: {theme_config['secondary']};
        }}
        
        QPushButton {{
            background-color: {theme_config['accent']};
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            font-weight: bold;
        }}
        
        QPushButton:hover {{
            background-color: {theme_config['accent']}cc;
        }}
        
        QPushButton:pressed {{
            background-color: {theme_config['accent']}aa;
        }}
        
        QPushButton:disabled {{
            background-color: #cccccc;
            color: #666666;
        }}
        
        QGroupBox {{
            font-weight: bold;
            border: 2px solid {theme_config['secondary']};
            border-radius: 5px;
            margin-top: 1ex;
            padding: 10px;
        }}
        
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }}
        """
        
        app.setStyleSheet(style)
