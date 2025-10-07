import sys
import serial
import serial.tools.list_ports
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QComboBox, QPushButton, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from qt_material import apply_stylesheet

# Worker để đọc dữ liệu từ cổng serial trong một thread riêng
class SerialWorker(QThread):
    data_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, port):
        super().__init__()
        self.port = port
        self.serial_port = None
        self._is_running = True

    def run(self):
        try:
            self.serial_port = serial.Serial(self.port, 115200, timeout=1)
        except serial.SerialException as e:
            self.error_occurred.emit(f"Không thể mở cổng {self.port}: {e}")
            return

        while self._is_running:
            if self.serial_port.in_waiting > 0:
                # Đợi byte Header
                if self.serial_port.read(1) == b'\xa5':
                    # Đọc Command và Length
                    command = self.serial_port.read(1)
                    length_byte = self.serial_port.read(1)
                    
                    if not command or not length_byte:
                        continue
                        
                    if command == b'\x01': # Lệnh UID
                        payload_len = int.from_bytes(length_byte, 'big')
                        
                        # Đọc payload, checksum và footer
                        payload = self.serial_port.read(payload_len)
                        checksum_byte = self.serial_port.read(1)
                        footer_byte = self.serial_port.read(1)

                        if len(payload) == payload_len and footer_byte == b'\x5a':
                            # Tính toán checksum
                            calculated_checksum = 0xA5 ^ 0x01 ^ payload_len
                            for byte in payload:
                                calculated_checksum ^= byte
                            
                            if calculated_checksum == int.from_bytes(checksum_byte, 'big'):
                                uid_hex = ' '.join(f'{b:02X}' for b in payload)
                                self.data_received.emit(uid_hex)
        
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()

    def stop(self):
        self._is_running = False
        self.wait()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STM32 NFC Reader")
        self.setGeometry(100, 100, 500, 350)
        
        self.serial_thread = None
        
        # --- UI Elements ---
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(15)

        # Connection Area
        connection_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setFont(QFont("Segoe UI", 10))
        self.connect_button = QPushButton("Kết nối")
        self.connect_button.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.connect_button.setMinimumHeight(35)
        connection_layout.addWidget(QLabel("Cổng COM:"))
        connection_layout.addWidget(self.port_combo)
        connection_layout.addWidget(self.connect_button)
        
        # Status Label
        self.status_label = QLabel("Chưa kết nối")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #fdd835;") # Yellow

        # UID Display Area
        self.uid_frame = QFrame()
        self.uid_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.uid_frame.setObjectName("uid_frame")
        self.uid_frame.setStyleSheet("#uid_frame { border: 1px solid #444; border-radius: 8px; }")
        
        uid_layout = QVBoxLayout(self.uid_frame)
        uid_title = QLabel("UID THẺ")
        uid_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        uid_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        
        self.uid_label = QLabel("---")
        self.uid_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.uid_label.setFont(QFont("Consolas", 24, QFont.Weight.Bold))
        self.uid_label.setStyleSheet("color: #4dd0e1;") # Cyan

        uid_layout.addWidget(uid_title)
        uid_layout.addWidget(self.uid_label)

        # Add widgets to main layout
        self.main_layout.addLayout(connection_layout)
        self.main_layout.addWidget(self.status_label)
        self.main_layout.addWidget(self.uid_frame)

        # --- Connections ---
        self.populate_ports()
        self.connect_button.clicked.connect(self.toggle_connection)
        
    def populate_ports(self):
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(port.device)

    def toggle_connection(self):
        if self.serial_thread is None:
            port = self.port_combo.currentText()
            if not port:
                self.status_label.setText("Lỗi: Không có cổng COM nào được chọn.")
                self.status_label.setStyleSheet("color: #e57373;") # Red
                return
            
            self.connect_button.setText("Ngắt kết nối")
            self.port_combo.setEnabled(False)
            self.status_label.setText(f"Đang kết nối đến {port}...")
            self.status_label.setStyleSheet("color: #81c784;") # Green

            self.serial_thread = SerialWorker(port)
            self.serial_thread.data_received.connect(self.update_uid)
            self.serial_thread.error_occurred.connect(self.handle_error)
            self.serial_thread.finished.connect(self.on_thread_finished)
            self.serial_thread.start()
        else:
            self.serial_thread.stop()
            self.serial_thread = None

    def update_uid(self, uid_hex):
        self.uid_label.setText(uid_hex)

    def handle_error(self, message):
        self.status_label.setText(f"Lỗi: {message}")
        self.status_label.setStyleSheet("color: #e57373;") # Red
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None
        self.connect_button.setText("Kết nối")
        self.port_combo.setEnabled(True)

    def on_thread_finished(self):
        if self._is_running: # Chỉ reset nếu không phải do người dùng chủ động ngắt
            self.status_label.setText("Đã ngắt kết nối")
            self.status_label.setStyleSheet("color: #fdd835;") # Yellow
            self.connect_button.setText("Kết nối")
            self.port_combo.setEnabled(True)

    def closeEvent(self, event):
        self._is_running = False
        if self.serial_thread:
            self.serial_thread.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Áp dụng theme hiện đại
    apply_stylesheet(app, theme='dark_teal.xml')
    
    window = MainWindow()
    window._is_running = True 
    window.show()
    
    sys.exit(app.exec())