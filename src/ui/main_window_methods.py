#!/usr/bin/env python3
"""
Additional methods for MainWindow class
Contains all the pattern builder, manual control, and settings methods
"""

from PyQt6.QtWidgets import QMessageBox, QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFileDialog
from PyQt6.QtCore import pyqtSlot, QTimer
from PyQt6.QtGui import QColor
from ..patterns.models import PatternStep
import time


class MainWindowMethods:
    """Mixin class containing all the MainWindow methods"""
    
    # Pattern Builder Methods
    def _on_pattern_name_changed(self):
        """Handle pattern name change"""
        self.current_pattern = self.current_pattern.with_name(self.pattern_name_edit.text())
        self._update_pattern_display()
    
    def _on_pattern_description_changed(self):
        """Handle pattern description change"""
        self.current_pattern = self.current_pattern.with_description(self.pattern_description.toPlainText())
    
    def _on_pattern_repetitions_changed(self, value):
        """Handle pattern repetitions change"""
        self.current_pattern = self.current_pattern.with_repetitions(value)
        self._update_pattern_display()
    
    @pyqtSlot()
    def _add_pattern_step(self):
        """Add step to current pattern"""
        try:
            needles = self.needles_spin.value()
            direction = self.direction_combo.currentText()
            rows = self.rows_spin.value()
            description = self.step_description_edit.text().strip()
            
            step = PatternStep(
                needles=needles, 
                direction=direction, 
                rows=rows, 
                description=description
            )
            
            # Add to pattern
            self.current_pattern = self.current_pattern.add_step(step)
            
            # Update display
            self._update_pattern_display()
            
            # Clear description field
            self.step_description_edit.clear()
            
            # Log the addition
            total_needles = needles * rows
            self._log_message(f"Added step: {needles} needles × {rows} rows = {total_needles} total needles {direction}")
            
        except Exception as e:
            self._show_error(f"Error adding step: {e}")
    
    @pyqtSlot()
    def _edit_selected_step(self):
        """Edit the selected pattern step"""
        current_row = self.steps_list.currentRow()
        if current_row >= 0 and current_row < len(self.current_pattern.steps):
            step = self.current_pattern.steps[current_row]
            
            # Create edit dialog
            dialog = QDialog(self)
            dialog.setWindowTitle("Edit Pattern Step")
            dialog.setModal(True)
            layout = QVBoxLayout(dialog)
            
            # Form fields
            form_layout = QGridLayout()
            
            from ..ui.components import NoWheelSpinBox, NoWheelComboBox
            from PyQt6.QtWidgets import QLineEdit
            
            needles_input = NoWheelSpinBox()
            needles_input.setMinimum(1)
            needles_input.setMaximum(10000)
            needles_input.setValue(step.needles)
            form_layout.addWidget(QLabel("Needles:"), 0, 0)
            form_layout.addWidget(needles_input, 0, 1)
            
            direction_combo = NoWheelComboBox()
            direction_combo.addItems(["CW", "CCW"])
            direction_combo.setCurrentText(step.direction)
            form_layout.addWidget(QLabel("Direction:"), 1, 0)
            form_layout.addWidget(direction_combo, 1, 1)
            
            rows_input = NoWheelSpinBox()
            rows_input.setMinimum(1)
            rows_input.setMaximum(1000)
            rows_input.setValue(step.rows)
            form_layout.addWidget(QLabel("Rows:"), 2, 0)
            form_layout.addWidget(rows_input, 2, 1)
            
            desc_input = QLineEdit(step.description)
            form_layout.addWidget(QLabel("Description:"), 3, 0)
            form_layout.addWidget(desc_input, 3, 1)
            
            layout.addLayout(form_layout)
            
            # Buttons
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Create updated step
                new_step = PatternStep(
                    needles=needles_input.value(),
                    direction=direction_combo.currentText(),
                    rows=rows_input.value(),
                    description=desc_input.text().strip()
                )
                
                # Update pattern
                steps = list(self.current_pattern.steps)
                steps[current_row] = new_step
                self.current_pattern = self.current_pattern.with_steps(steps)
                
                self._update_pattern_display()
                self._log_message(f"Edited step {current_row + 1}")
    
    @pyqtSlot()
    def _remove_pattern_step(self):
        """Remove selected step from pattern"""
        current_row = self.steps_list.currentRow()
        if current_row >= 0 and current_row < len(self.current_pattern.steps):
            step = self.current_pattern.steps[current_row]
            reply = QMessageBox.question(
                self, "Delete Step", 
                f"Delete step: {step.description or 'Unnamed step'}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                steps = list(self.current_pattern.steps)
                steps.pop(current_row)
                self.current_pattern = self.current_pattern.with_steps(steps)
                self._update_pattern_display()
                self._log_message(f"Deleted step {current_row + 1}")
    
    @pyqtSlot()
    def _move_step_up(self):
        """Move selected step up"""
        current_row = self.steps_list.currentRow()
        if current_row > 0:
            steps = list(self.current_pattern.steps)
            steps[current_row], steps[current_row - 1] = steps[current_row - 1], steps[current_row]
            self.current_pattern = self.current_pattern.with_steps(steps)
            
            self._update_pattern_display()
            self.steps_list.setCurrentRow(current_row - 1)
            self._log_message(f"Moved step {current_row + 1} up")
    
    @pyqtSlot()
    def _move_step_down(self):
        """Move selected step down"""
        current_row = self.steps_list.currentRow()
        if current_row >= 0 and current_row < len(self.current_pattern.steps) - 1:
            steps = list(self.current_pattern.steps)
            steps[current_row], steps[current_row + 1] = steps[current_row + 1], steps[current_row]
            self.current_pattern = self.current_pattern.with_steps(steps)
            
            self._update_pattern_display()
            self.steps_list.setCurrentRow(current_row + 1)
            self._log_message(f"Moved step {current_row + 1} down")
    
    def _update_pattern_display(self):
        """Update the pattern steps display and visual table"""
        # Update steps list
        self.steps_list.clear()
        
        total_needles = 0
        for i, step in enumerate(self.current_pattern.steps):
            step_needles = step.total_needles  # needles * rows
            total_needles += step_needles
            
            # Create display text
            rows_text = f" × {step.rows} rows" if step.rows > 1 else ""
            display_text = f"{i+1}. {step.needles} needles{rows_text} {step.direction} = {step_needles} total"
            if step.description:
                display_text += f" - {step.description}"
            
            from PyQt6.QtWidgets import QListWidgetItem
            item = QListWidgetItem(display_text)
            
            # Color code by direction
            if step.direction == "CW":
                item.setBackground(QColor("#E8F5E8"))  # Light green
            else:
                item.setBackground(QColor("#FFF0F0"))  # Light red
            
            self.steps_list.addItem(item)
        
        # Update visual pattern table
        self._update_pattern_visual()
    
    def _update_pattern_visual(self):
        """Create Excel-like table visualization"""
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor
        
        # Clear table
        self.pattern_table.clear()
        
        step_count = len(self.current_pattern.steps)
        if step_count == 0:
            # Show empty state
            self.pattern_table.setRowCount(1)
            self.pattern_table.setColumnCount(1)
            self.pattern_table.setHorizontalHeaderLabels(["Pattern"])
            self.pattern_table.setVerticalHeaderLabels(["Info"])
            
            item = QTableWidgetItem("Add steps to see pattern preview")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.pattern_table.setItem(0, 0, item)
            self.pattern_info_label.setText("No pattern created yet")
            return
        
        # Calculate grid dimensions
        max_needles = 0
        total_rows = 0
        
        for step in self.current_pattern.steps:
            max_needles = max(max_needles, step.needles)
            total_rows += step.rows
        
        # Account for repetitions
        total_rows_with_reps = total_rows * self.current_pattern.repetitions
        
        # Set up table
        self.pattern_table.setRowCount(total_rows_with_reps)
        self.pattern_table.setColumnCount(max_needles)
        
        # Column headers
        column_headers = [f"N{i+1}" for i in range(max_needles)]
        self.pattern_table.setHorizontalHeaderLabels(column_headers)
        
        # Fill table
        current_row = 0
        
        for rep in range(self.current_pattern.repetitions):
            for step_idx, step in enumerate(self.current_pattern.steps):
                # Colors for direction
                if step.direction == "CW":
                    bg_color = QColor("#E3F2FD")  # Light blue
                    symbol = "↻"
                else:
                    bg_color = QColor("#FFEBEE")  # Light red
                    symbol = "↺"
                
                # Fill rows for this step
                for row in range(step.rows):
                    # Row header
                    row_label = f"R{current_row + 1}"
                    if self.current_pattern.repetitions > 1:
                        row_label += f" (Rep {rep + 1}, Step {step_idx + 1})"
                    else:
                        row_label += f" (Step {step_idx + 1})"
                    
                    from PyQt6.QtWidgets import QTableWidgetItem as QTItem
                    self.pattern_table.setVerticalHeaderItem(current_row, QTItem(row_label))
                    
                    # Fill needle columns
                    for needle in range(max_needles):
                        item = QTItem()
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                        
                        if needle < step.needles:
                            item.setText(f"{step.direction}\n{symbol}")
                            item.setBackground(bg_color)
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        else:
                            item.setText("-")
                            item.setBackground(QColor("#F5F5F5"))
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        
                        self.pattern_table.setItem(current_row, needle, item)
                    
                    current_row += 1
        
        # Resize table
        self.pattern_table.resizeColumnsToContents()
        
        # Update info label
        total_needles = sum(step.total_needles for step in self.current_pattern.steps)
        total_with_reps = total_needles * self.current_pattern.repetitions
        rep_text = f" (×{self.current_pattern.repetitions} = {total_with_reps} total)" if self.current_pattern.repetitions > 1 else ""
        avg_needles = total_needles / step_count if step_count > 0 else 0
        
        self.pattern_info_label.setText(
            f"Grid: {total_rows_with_reps} rows × {max_needles} needles | "
            f"Pattern: {step_count} steps, {total_needles} needles per cycle{rep_text} | "
            f"Blue=CW ↻, Red=CCW ↺ | Average: {avg_needles:.1f} needles/step"
        )
    
    @pyqtSlot()
    def _save_current_pattern(self):
        """Save current pattern"""
        if not self.current_pattern.steps:
            QMessageBox.warning(self, "Save Pattern", "Cannot save empty pattern!")
            return
        
        # Check if pattern exists
        existing_pattern = None
        for pattern in self.saved_patterns:
            if pattern.name == self.current_pattern.name:
                existing_pattern = pattern
                break
        
        if existing_pattern:
            reply = QMessageBox.question(
                self, "Pattern Exists", 
                f"Pattern '{self.current_pattern.name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
            
            # Replace existing
            index = self.saved_patterns.index(existing_pattern)
            self.saved_patterns[index] = self.current_pattern
        else:
            # Add new pattern
            self.saved_patterns.append(self.current_pattern)
        
        # Save to file
        self._save_patterns()
        self._log_message(f"Pattern '{self.current_pattern.name}' saved successfully")
    
    @pyqtSlot()
    def _show_load_pattern_dialog(self):
        """Show load pattern dialog"""
        if not self.saved_patterns:
            QMessageBox.information(self, "Load Pattern", "No saved patterns available!")
            return
        
        # Create dialog
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QListWidget
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Load Pattern")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("Select pattern to load:"))
        
        pattern_list = QListWidget()
        for pattern in self.saved_patterns:
            total_needles = sum(step.total_needles for step in pattern.steps)
            item_text = f"{pattern.name} ({len(pattern.steps)} steps, {total_needles} needles)"
            pattern_list.addItem(item_text)
        
        layout.addWidget(pattern_list)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_row = pattern_list.currentRow()
            if selected_row >= 0:
                self._load_pattern(self.saved_patterns[selected_row])
    
    def _load_pattern(self, pattern):
        """Load pattern into editor"""
        self.current_pattern = pattern
        
        # Update UI
        self.pattern_name_edit.setText(self.current_pattern.name)
        self.pattern_description.setPlainText(self.current_pattern.description)
        self.repetitions_spin.setValue(self.current_pattern.repetitions)
        self._update_pattern_display()
        
        self._log_message(f"Loaded pattern '{pattern.name}'")
    
    @pyqtSlot()
    def _new_pattern(self):
        """Create new empty pattern"""
        if self.current_pattern.steps:
            reply = QMessageBox.question(
                self, "New Pattern",
                "Current pattern will be lost. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        from ..patterns.models import KnittingPattern
        self.current_pattern = KnittingPattern.empty("New Pattern")
        self.pattern_name_edit.setText(self.current_pattern.name)
        self.pattern_description.setPlainText("")
        self.repetitions_spin.setValue(self.current_pattern.repetitions)
        self._update_pattern_display()
        
        self._log_message("Created new pattern")
    
    @pyqtSlot()
    def _execute_current_pattern(self):
        """Execute the current pattern"""
        if not self.current_pattern.steps:
            QMessageBox.warning(self, "Execute Pattern", "No steps in current pattern!")
            return
        
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Execution Error", "Please connect to Arduino first!")
            return
        
        # Start pattern execution
        self._start_pattern_execution()
    
    def _start_pattern_execution(self):
        """Start executing pattern"""
        self.pattern_execution_index = 0
        self.pattern_repetition_index = 0
        self.pattern_execution_stopped = False
        
        total_steps = len(self.current_pattern.steps) * self.current_pattern.repetitions
        self._log_message(f"Starting pattern execution: '{self.current_pattern.name}' "
                         f"({len(self.current_pattern.steps)} steps × {self.current_pattern.repetitions} reps = {total_steps} total)")
        
        # Show progress dialog
        from ..ui.components import ProgressDialog
        self.progress_dialog = ProgressDialog("Executing Pattern", self)
        self.progress_dialog.stop_btn.clicked.connect(self._stop_pattern_execution)
        self.progress_dialog.emergency_btn.clicked.connect(self._emergency_stop)
        self.progress_dialog.show()
        
        self._execute_next_pattern_step()
    
    def _execute_next_pattern_step(self):
        """Execute next step in pattern"""
        if self.pattern_execution_stopped:
            self._log_message("Pattern execution stopped by user")
            if self.progress_dialog:
                self.progress_dialog.close()
                self.progress_dialog = None
            return
        
        if self.pattern_execution_index >= len(self.current_pattern.steps):
            # Finished current repetition
            self.pattern_repetition_index += 1
            if self.pattern_repetition_index >= self.current_pattern.repetitions:
                # All repetitions complete
                self._log_message(f"Pattern execution completed! "
                                f"Executed {self.current_pattern.repetitions} repetitions")
                if self.progress_dialog:
                    self.progress_dialog.close()
                    self.progress_dialog = None
                return
            else:
                # Start next repetition
                self.pattern_execution_index = 0
                self._log_message(f"Starting repetition {self.pattern_repetition_index + 1}/{self.current_pattern.repetitions}")
        
        # Get current step
        step = self.current_pattern.steps[self.pattern_execution_index]
        
        # Log step execution
        step_num = self.pattern_execution_index + 1
        rep_num = self.pattern_repetition_index + 1
        total_steps = len(self.current_pattern.steps)
        total_reps = self.current_pattern.repetitions
        
        total_needles_for_step = step.total_needles
        
        self._log_message(f"Executing step {step_num}/{total_steps} (repetition {rep_num}/{total_reps}): "
                         f"{step.needles} needles × {step.rows} rows = {total_needles_for_step} total needles {step.direction}")
        
        # Send command
        command = f"NEEDLE_TARGET:{total_needles_for_step}:{step.direction}"
        if self.serial_manager.send_command_async(command):
            self.pattern_execution_index += 1
            # Continue with next step after delay
            QTimer.singleShot(100, self._execute_next_pattern_step)
        else:
            self._log_message("Failed to send command")
            self._stop_pattern_execution()
    
    @pyqtSlot()
    def _stop_pattern_execution(self):
        """Stop pattern execution"""
        self.pattern_execution_stopped = True
        self.serial_manager.send_command("STOP")
        self.pattern_execution_index = 0
        self.pattern_repetition_index = 0
        self._log_message("Pattern execution stopped")
        
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
    
    # Manual Control Methods
    @pyqtSlot()
    def _home_machine(self):
        """Home the machine to needle 0"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Control Error", "Please connect to Arduino first")
            return
        
        # Calculate steps to home (go to position 0)
        if self.current_needle_position != 0:
            # Determine shortest path to home
            steps_cw = (self.total_needles_on_machine - self.current_needle_position) * self.config.get("steps_per_needle", 1000)
            steps_ccw = self.current_needle_position * self.config.get("steps_per_needle", 1000)
            
            if steps_ccw <= steps_cw:
                # Go counter-clockwise (shorter path)
                command = f"TURN:{steps_ccw}:CCW"
                self._log_message(f"Homing via CCW: {steps_ccw} steps")
            else:
                # Go clockwise
                command = f"TURN:{steps_cw}:CW"
                self._log_message(f"Homing via CW: {steps_cw} steps")
            
            if self.serial_manager.send_command_async(command):
                self.current_needle_position = 0
                self.current_needle_display.setText("0")
                self.position_label.setText("Position: Needle 0 (Home)")
        else:
            self._log_message("Already at home position")
    
    @pyqtSlot()
    def _emergency_stop(self):
        """Emergency stop"""
        self.pattern_execution_stopped = True
        
        # Send multiple stop commands
        if self.serial_manager.is_connected():
            self.serial_manager.send_command("STOP")
            self.serial_manager.send_command("EMERGENCY_STOP")
            self.serial_manager.send_command("HALT")
        
        self._log_message("EMERGENCY STOP - Machine halted!")
        
        # Close any progress dialogs
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        QMessageBox.warning(self, "Emergency Stop", 
                          "Machine has been stopped immediately!\nAll operations have been halted.")
    
    @pyqtSlot()
    def _start_needle_target_mode(self):
        """Start needle target mode"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Control Error", "Please connect to Arduino first")
            return
        
        target_needles = self.needle_target_spin.value()
        direction = self.needle_direction_combo.currentText()
        
        # Confirmation dialog
        reply = QMessageBox.question(
            self, "Needle Target Mode",
            f"Motor will run {direction} until {target_needles} needles are counted.\n"
            f"Current needle count will be the starting point.\n"
            f"You can stop anytime with the STOP button.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Start needle monitoring if not already running
        if not self.needle_monitoring_enabled:
            self._toggle_needle_monitoring()
        
        # Send needle target command
        command = f"NEEDLE_TARGET:{target_needles}:{direction}"
        if self.serial_manager.send_command_async(command):
            self._log_message(f"Needle target mode started: {target_needles} needles {direction}")
        else:
            self._log_message("Failed to start needle target mode")
    
    @pyqtSlot()
    def _toggle_needle_monitoring(self):
        """Toggle needle monitoring"""
        if self.needle_monitoring_enabled:
            # Stop monitoring
            self.needle_timer.stop()
            self.needle_monitoring_enabled = False
            self.monitor_needle_btn.setText("Start Needle Monitoring")
            self.monitoring_label.setText("Monitoring: Off")
            self.monitoring_label.setStyleSheet("QLabel { color: #666; }")
            self._log_message("Needle monitoring stopped")
        else:
            # Start monitoring
            if self.connect_btn.text() != "Disconnect":
                QMessageBox.warning(self, "Monitoring Error", "Please connect to Arduino first")
                return
            
            self.needle_monitoring_enabled = True
            self.needle_timer.start(500)  # Check every 500ms
            self.monitor_needle_btn.setText("Stop Needle Monitoring")
            self.monitoring_label.setText("Monitoring: Active")
            self.monitoring_label.setStyleSheet("QLabel { color: #4CAF50; }")
            self._log_message("Needle monitoring started")
    
    def _update_needle_reading(self):
        """Update needle reading from Arduino"""
        if self.serial_manager.is_connected():
            self.serial_manager.send_command_async("NEEDLE_COUNT")
    
    @pyqtSlot()
    def _reset_needle_position(self):
        """Reset needle position counter"""
        self.current_needle_position = 0
        self.current_needle_display.setText("0")
        self.position_label.setText("Position: Needle 0 (Reset)")
        self._log_message("Needle position reset to 0")
    
    @pyqtSlot()
    def _show_needle_count_window(self):
        """Show dedicated needle count window"""
        # This could be expanded to show a larger, dedicated window for needle counting
        QMessageBox.information(self, "Needle Count", 
                              f"Current needle position: {self.current_needle_position}\n"
                              f"Total needles on machine: {self.total_needles_on_machine}")
    
    @pyqtSlot()
    def _manual_turn(self):
        """Execute manual turn"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Control Error", "Please connect to Arduino first")
            return
        
        steps = self.manual_steps_spin.value()
        direction = self.manual_direction_combo.currentText()
        command = f"TURN:{steps}:{direction}"
        
        if self.serial_manager.send_command_async(command):
            self._log_message(f"Manual turn: {steps} steps {direction}")
        else:
            self._log_message("Failed to send manual turn command")
    
    @pyqtSlot()
    def _send_custom_command(self):
        """Send custom Arduino command"""
        command = self.custom_command_edit.text().strip()
        if not command:
            return
        
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Control Error", "Please connect to Arduino first")
            return
        
        if self.serial_manager.send_command_async(command):
            self._log_message(f"Sent custom command: {command}")
            self.custom_command_edit.clear()
        else:
            self._log_message(f"Failed to send custom command: {command}")
    
    # Script execution methods
    @pyqtSlot()
    def _browse_script_file(self):
        """Browse for script file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Script File", "", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    content = f.read().strip()
                
                self.file_path_edit.setText(file_path)
                self.script_content.setText(content)
                
                # Parse script info
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                command_count = len(lines)
                total_steps = 0
                
                for line in lines:
                    if line.startswith("TURN:"):
                        parts = line.split(":")
                        if len(parts) >= 2:
                            try:
                                total_steps += int(parts[1])
                            except ValueError:
                                pass
                
                info_text = f"Commands: {command_count}, Total Steps: {total_steps:,}"
                self.script_info_label.setText(info_text)
                self.upload_btn.setEnabled(True)
                
                self.loaded_script = lines
                self._log_message(f"Script loaded: {file_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "Load Error", f"Failed to load script: {str(e)}")
    
    @pyqtSlot()
    def _execute_script(self):
        """Execute loaded script"""
        if not hasattr(self, 'loaded_script'):
            QMessageBox.warning(self, "Execute Error", "Please load a script first")
            return
        
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Execute Error", "Please connect to Arduino first")
            return
        
        # Show progress dialog
        from ..ui.components import ProgressDialog
        self.progress_dialog = ProgressDialog("Executing Script", self)
        self.progress_dialog.stop_btn.clicked.connect(self._stop_script)
        self.progress_dialog.emergency_btn.clicked.connect(self._emergency_stop)
        self.progress_dialog.show()
        
        # Start script execution
        self.serial_manager.queue_commands(self.loaded_script)
        self._log_message(f"Starting script execution: {len(self.loaded_script)} commands")
    
    @pyqtSlot()
    def _stop_script(self):
        """Stop script execution"""
        self.serial_manager.stop_operation()
        self._log_message("Script execution stopped")
        
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
    
    # Settings methods
    @pyqtSlot(str)
    def _on_theme_changed(self, theme):
        """Handle theme change"""
        self.current_theme = theme
        self.config["theme"] = theme
        self._save_config()
        self._apply_theme()
        self._log_message(f"Theme changed to: {theme}")
    
    @pyqtSlot(int)
    def _on_speed_changed(self, value):
        """Handle speed change"""
        self.config["motor_speed"] = value
        self._save_config()
    
    def _set_speed_preset(self, speed):
        """Set speed preset"""
        self.speed_spin.setValue(speed)
        self.config["motor_speed"] = speed
        self._save_config()
    
    @pyqtSlot()
    def _apply_speed_setting(self):
        """Apply speed setting to Arduino"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Settings Error", "Please connect to Arduino first")
            return
        
        speed = self.speed_spin.value()
        command = f"SPEED:{speed}"
        if self.serial_manager.send_command_async(command):
            self._log_message(f"Applied motor speed: {speed}μs")
        else:
            self._log_message("Failed to apply speed setting")
    
    @pyqtSlot(int)
    def _on_chunk_size_changed(self, value):
        """Handle chunk size change"""
        self.config["chunk_size"] = value
        self._save_config()
    
    @pyqtSlot()
    def _refresh_current_settings(self):
        """Refresh current Arduino settings"""
        if self.connect_btn.text() != "Disconnect":
            QMessageBox.warning(self, "Settings Error", "Please connect to Arduino first")
            return
        
        if self.serial_manager.send_command_async("STATUS"):
            self._log_message("Requesting current Arduino settings...")
            # Update display after delay
            QTimer.singleShot(1000, self._update_settings_display)
        else:
            self._log_message("Failed to request Arduino settings")
    
    def _update_settings_display(self):
        """Update settings display"""
        settings_text = f"""Motor Speed: {self.config['motor_speed']}μs
Steps per Needle: {self.config['steps_per_needle']}
Chunk Size: {self.config['chunk_size']} steps
Total Needles: {self.config['total_needles']}"""
        self.current_settings_label.setText(settings_text)
    
    # Utility methods
    def _check_for_responses(self):
        """Check for Arduino responses"""
        # This would be called by the response checker timer
        pass
    
    def _update_status(self):
        """Update status display"""
        # Update connection status and other periodic updates
        pass
    
    def _show_error(self, message: str):
        """Show error message"""
        QMessageBox.critical(self, "Error", message)
    
    def _show_info(self, message: str):
        """Show info message"""
        QMessageBox.information(self, "Information", message)
    
    # Theme application methods
    def _apply_pink_theme(self):
        """Apply pink/rose theme"""
        self.setStyleSheet("""
            QMainWindow { background-color: white; color: #333333; }
            QWidget { background-color: white; color: #333333; }
            QLabel { color: #333333; font-size: 14px; }
            QGroupBox { 
                color: #333333; font-weight: bold; border: 2px solid #e0e0e0; 
                border-radius: 8px; margin-top: 1ex; padding-top: 15px; 
                background-color: #fafafa; font-size: 14px;
            }
            QGroupBox::title { 
                subcontrol-origin: margin; left: 10px; padding: 0 8px 0 8px; 
                color: #e91e63; font-weight: bold; font-size: 15px; 
            }
            QPushButton { 
                background-color: #e91e63; color: white; border: none; 
                padding: 10px 20px; border-radius: 6px; font-weight: 500; 
                font-size: 14px; min-height: 25px; 
            }
            QPushButton:hover { background-color: #c2185b; }
            QPushButton:pressed { background-color: #ad1457; }
            QPushButton:disabled { background-color: #e0e0e0; color: #9e9e9e; }
            QLineEdit, QSpinBox, QComboBox { 
                padding: 10px; border: 2px solid #e0e0e0; border-radius: 6px; 
                font-size: 14px; background-color: white; min-height: 20px; 
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #e91e63; }
            QTextEdit { 
                border: 2px solid #e0e0e0; border-radius: 6px; padding: 8px; 
                font-size: 13px; background-color: white; 
            }
            QTextEdit:focus { border-color: #e91e63; }
            QTabWidget::pane { border: 2px solid #e0e0e0; border-radius: 8px; }
            QTabBar::tab { 
                background-color: #f5f5f5; color: #666666; padding: 12px 20px; 
                margin-right: 4px; border-top-left-radius: 6px; 
                border-top-right-radius: 6px; font-size: 14px; min-width: 120px; 
            }
            QTabBar::tab:selected { background-color: #e91e63; color: white; }
            QTabBar::tab:hover:!selected { background-color: #fce4ec; color: #e91e63; }
            QListWidget { 
                border: 2px solid #e0e0e0; border-radius: 6px; 
                background-color: white; font-size: 14px; padding: 4px; 
            }
            QListWidget::item { padding: 8px; margin: 2px; border-radius: 4px; }
            QListWidget::item:selected { background-color: #e91e63; color: white; }
            QListWidget::item:hover:!selected { background-color: #fce4ec; }
            QProgressBar { 
                border: 2px solid #e0e0e0; border-radius: 8px; 
                background-color: white; text-align: center; font-weight: bold; 
            }
            QProgressBar::chunk { background-color: #e91e63; border-radius: 6px; }
        """)
    
    def _apply_dark_theme(self):
        """Apply dark theme"""
        self.setStyleSheet("""
            QMainWindow { background-color: #2b2b2b; color: #ffffff; }
            QWidget { background-color: #2b2b2b; color: #ffffff; }
            QLabel { color: #ffffff; font-size: 14px; }
            QGroupBox { 
                color: #ffffff; font-weight: bold; border: 2px solid #555555; 
                border-radius: 8px; margin-top: 1ex; padding-top: 15px; 
                background-color: #3a3a3a; font-size: 14px;
            }
            QGroupBox::title { 
                subcontrol-origin: margin; left: 10px; padding: 0 8px 0 8px; 
                color: #64b5f6; font-weight: bold; font-size: 15px; 
            }
            QPushButton { 
                background-color: #64b5f6; color: white; border: none; 
                padding: 10px 20px; border-radius: 6px; font-weight: 500; 
                font-size: 14px; min-height: 25px; 
            }
            QPushButton:hover { background-color: #42a5f5; }
            QPushButton:pressed { background-color: #1e88e5; }
            QPushButton:disabled { background-color: #555555; color: #888888; }
            QLineEdit, QSpinBox, QComboBox { 
                padding: 10px; border: 2px solid #555555; border-radius: 6px; 
                font-size: 14px; color: #ffffff; background-color: #3a3a3a; 
            }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #64b5f6; }
            QTextEdit { 
                border: 2px solid #555555; border-radius: 6px; padding: 8px; 
                font-size: 13px; color: #ffffff; background-color: #3a3a3a; 
            }
            QTextEdit:focus { border-color: #64b5f6; }
            QTabWidget::pane { border: 2px solid #555555; border-radius: 8px; }
            QTabBar::tab { 
                background-color: #3a3a3a; color: #ffffff; padding: 12px 20px; 
                margin-right: 4px; border-top-left-radius: 6px; 
                border-top-right-radius: 6px; font-size: 14px; min-width: 120px; 
            }
            QTabBar::tab:selected { background-color: #64b5f6; color: white; }
            QTabBar::tab:hover:!selected { background-color: #4a4a4a; color: #64b5f6; }
        """)
    
    def _apply_light_theme(self):
        """Apply light/grey theme"""
        self.setStyleSheet("""
            QMainWindow { background-color: #f5f5f5; color: #2e2e2e; }
            QWidget { background-color: #f5f5f5; color: #2e2e2e; }
            QLabel { color: #2e2e2e; font-size: 14px; }
            QGroupBox { 
                color: #2e2e2e; font-weight: bold; border: 2px solid #cccccc; 
                border-radius: 8px; margin-top: 1ex; padding-top: 15px; 
                background-color: #ffffff; font-size: 14px;
            }
            QGroupBox::title { 
                subcontrol-origin: margin; left: 10px; padding: 0 8px 0 8px; 
                color: #607d8b; font-weight: bold; font-size: 15px; 
            }
            QPushButton { 
                background-color: #607d8b; color: white; border: none; 
                padding: 10px 20px; border-radius: 6px; font-weight: 500; 
                font-size: 14px; min-height: 25px; 
            }
            QPushButton:hover { background-color: #546e7a; }
            QPushButton:pressed { background-color: #455a64; }
            QPushButton:disabled { background-color: #e0e0e0; color: #9e9e9e; }
        """)
    
    # Controller event handlers
    def _on_state_change(self, new_state):
        """Handle machine state changes"""
        self._log_message(f"Machine state changed to: {new_state.value}")
    
    def _on_progress_update(self, status):
        """Handle progress updates"""
        if self.progress_dialog:
            self.progress_dialog.update_progress(status.current_step, status.total_steps)
    
    def _on_error(self, error_message: str):
        """Handle error notifications"""
        self._show_error(error_message)
    
    def closeEvent(self, event):
        """Handle application close"""
        if hasattr(self, 'controller'):
            self.controller.cleanup()
        if hasattr(self, 'serial_manager'):
            self.serial_manager.disconnect()
        event.accept()
