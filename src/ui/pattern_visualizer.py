#!/usr/bin/env python3
"""
Pattern Visualization Component
Excel-like grid display for knitting patterns
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox
from PyQt6.QtCore import Qt
from typing import Optional

from ..patterns.models import KnittingPattern
from .components import OptimizedTableWidget


class PatternVisualizer(QWidget):
    """Widget for visualizing knitting patterns in Excel-like grid"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.current_pattern: Optional[KnittingPattern] = None
    
    def _setup_ui(self):
        """Setup the visualization UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Group box container
        group_box = QGroupBox("Pattern Visualization")
        group_layout = QVBoxLayout(group_box)
        
        # Pattern table
        self.pattern_table = OptimizedTableWidget()
        self.pattern_table.setMinimumHeight(200)
        self.pattern_table.setMaximumHeight(400)
        group_layout.addWidget(self.pattern_table)
        
        # Info label
        self.info_label = QLabel("No pattern loaded")
        self.info_label.setStyleSheet("font-size: 12px; color: #666; padding: 5px;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setWordWrap(True)
        group_layout.addWidget(self.info_label)
        
        layout.addWidget(group_box)
    
    def display_pattern(self, pattern: KnittingPattern):
        """Display pattern in Excel-like grid format"""
        self.current_pattern = pattern
        
        if not pattern.steps:
            self._show_empty_state()
            return
        
        try:
            # Calculate grid dimensions
            max_needles = max(step.needles for step in pattern.steps)
            total_rows = sum(step.rows for step in pattern.steps) * pattern.repetitions
            
            # Setup table data callback
            def get_cell_data(row: int, col: int) -> tuple:
                """Get data for specific cell (text, bg_color, text_color)"""
                return self._calculate_cell_data(row, col, pattern, max_needles)
            
            # Populate table efficiently
            self.pattern_table.populate_grid(total_rows, max_needles, get_cell_data)
            
            # Update info label
            self._update_info_label(pattern, total_rows, max_needles)
            
        except Exception as e:
            self.info_label.setText(f"Error displaying pattern: {e}")
    
    def clear_pattern(self):
        """Clear current pattern display"""
        self.current_pattern = None
        self.pattern_table.clear_efficiently()
        self.info_label.setText("No pattern loaded")
    
    def _show_empty_state(self):
        """Show empty pattern state"""
        self.pattern_table.clear_efficiently()
        self.pattern_table.setRowCount(1)
        self.pattern_table.setColumnCount(1)
        self.pattern_table.setHorizontalHeaderLabels(["Pattern"])
        self.pattern_table.setVerticalHeaderLabels(["Info"])
        
        from PyQt6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem("Add steps to see pattern preview")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.pattern_table.setItem(0, 0, item)
        self.pattern_table.resizeColumnsToContents()
        
        self.info_label.setText("No pattern steps defined")
    
    def _calculate_cell_data(self, row: int, col: int, pattern: KnittingPattern, max_needles: int) -> tuple:
        """Calculate cell display data"""
        try:
            # Find which step and repetition this row belongs to
            current_row = row
            current_rep = 0
            step_in_rep = 0
            row_in_step = 0
            
            # Calculate position within pattern structure
            rows_per_rep = sum(step.rows for step in pattern.steps)
            
            if rows_per_rep > 0:
                current_rep = current_row // rows_per_rep
                remaining_rows = current_row % rows_per_rep
                
                # Find step within repetition
                rows_passed = 0
                for step_idx, step in enumerate(pattern.steps):
                    if remaining_rows < rows_passed + step.rows:
                        step_in_rep = step_idx
                        row_in_step = remaining_rows - rows_passed
                        break
                    rows_passed += step.rows
                
                # Get step info
                if step_in_rep < len(pattern.steps):
                    step = pattern.steps[step_in_rep]
                    
                    if col < step.needles:
                        # This needle is used in this step
                        if step.direction == "CW":
                            return ("CW\\n↻", "#E3F2FD", "#1976D2")  # Light blue bg, dark blue text
                        else:
                            return ("CCW\\n↺", "#FFEBEE", "#D32F2F")  # Light red bg, dark red text
                    else:
                        # This needle is not used
                        return ("-", "#F5F5F5", "#999999")  # Gray bg and text
            
            return ("", "#FFFFFF", "#000000")  # Default white
            
        except Exception:
            return ("?", "#FFE0E0", "#CC0000")  # Error state - light red
    
    def _update_info_label(self, pattern: KnittingPattern, total_rows: int, max_needles: int):
        """Update the information label"""
        try:
            total_needles = pattern.total_needles
            step_count = len(pattern.steps)
            rep_text = f" (×{pattern.repetitions})" if pattern.repetitions > 1 else ""
            avg_needles = sum(step.needles for step in pattern.steps) / step_count if step_count > 0 else 0
            
            info_text = (
                f"Grid: {total_rows} rows × {max_needles} needles | "
                f"Pattern: {step_count} steps{rep_text}, {total_needles} total needles | "
                f"Blue=CW ↻, Red=CCW ↺ | Average: {avg_needles:.1f} needles/step"
            )
            
            self.info_label.setText(info_text)
            
        except Exception as e:
            self.info_label.setText(f"Pattern info unavailable: {e}")
    
    def get_current_pattern(self) -> Optional[KnittingPattern]:
        """Get currently displayed pattern"""
        return self.current_pattern
