import sys
import serial
import serial.tools.list_ports
import math
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QComboBox, QPushButton, QFrame,
                             QGraphicsView, QGraphicsScene, QGraphicsRectItem)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRectF
from PyQt6.QtGui import QFont, QColor, QBrush, QPen
from qt_material import apply_stylesheet

# Worker để đọc dữ liệu từ cổng serial trong một thread riêng
class SerialWorker(QThread):
    nfc_data_received = pyqtSignal(str)
    thermal_data_received = pyqtSignal(list)
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
                if self.serial_port.read(1) == b'\xa5': # Header
                    command = self.serial_port.read(1)
                    length_byte = self.serial_port.read(1)
                    
                    if not command or not length_byte: continue
                    
                    payload_len = int.from_bytes(length_byte, 'big')
                    
                    # Chờ đủ dữ liệu (payload + checksum + footer)
                    while self.serial_port.in_waiting < payload_len + 2:
                        self.msleep(5)

                    payload = self.serial_port.read(payload_len)
                    checksum_byte = self.serial_port.read(1)
                    footer_byte = self.serial_port.read(1)
                    
                    if len(payload) != payload_len or footer_byte != b'\x5a': continue
                    
                    # Xử lý lệnh NFC
                    if command == b'\x01':
                        uid_hex = ' '.join(f'{b:02X}' for b in payload)
                        self.nfc_data_received.emit(uid_hex)
                    # Xử lý lệnh Thermal
                    elif command == b'\x11' and payload_len == 128:
                        temps = []
                        for i in range(0, 128, 2):
                            high_byte = payload[i]
                            low_byte = payload[i+1]
                            # Kết hợp 2 byte thành int16
                            temp_int = int.from_bytes([high_byte, low_byte], byteorder='big', signed=True)
                            temps.append(temp_int / 100.0)
                        if len(temps) == 64:
                            self.thermal_data_received.emit(temps)
        
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()

    def send_command(self, command, payload=b''):
        if self.serial_port and self.serial_port.is_open:
            header = b'\xA5'
            cmd_byte = command.to_bytes(1, 'big')
            len_byte = len(payload).to_bytes(1, 'big')
            
            checksum = header[0] ^ cmd_byte[0] ^ len_byte[0]
            for byte in payload:
                checksum ^= byte
            
            checksum_byte = checksum.to_bytes(1, 'big')
            footer = b'\x5A'
            
            frame = header + cmd_byte + len_byte + payload + checksum_byte + footer
            self.serial_port.write(frame)

    def stop(self):
        self._is_running = False
        self.wait()

class ThermalGridView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setFixedSize(240, 240)
        self.pixels = []
        for _ in range(64):
            rect = QGraphicsRectItem(QRectF(0, 0, 30, 30))
            rect.setPen(QPen(Qt.PenStyle.NoPen))
            self.pixels.append(rect)
            self.scene.addItem(rect)
            
    def get_color_for_temp(self, temp, min_temp=20, max_temp=35):
        temp = max(min_temp, min(temp, max_temp))
        ratio = (temp - min_temp) / (max_temp - min_temp)
        # Blue -> Green -> Red
        r = int(max(0, 255 * (ratio * 2 - 1)))
        g = int(max(0, 255 * (1 - abs(ratio - 0.5) * 2)))
        b = int(max(0, 255 * (1 - ratio * 2)))
        return QColor(r, g, b)
        
    def update_grid(self, temps):
        if len(temps) != 64: return
        for i, temp in enumerate(temps):
            row = i // 8
            col = i % 8
            rect = self.pixels[i]
            rect.setPos(col * 30, row * 30)
            rect.setBrush(QBrush(self.get_color_for_temp(temp)))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STM32 NFC & Thermal Reader")
        self.setGeometry(100, 100, 700, 420)
        self.serial_thread = None
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        # --- Cột điều khiển (trái) ---
        control_widget = QWidget()
        control_layout = QVBoxLayout(control_widget)
        
        connection_layout = QHBoxLayout()
        self.port_combo = QComboBox()
        self.connect_button = QPushButton("Kết nối")
        connection_layout.addWidget(QLabel("Cổng COM:"))
        connection_layout.addWidget(self.port_combo)
        connection_layout.addWidget(self.connect_button)
        
        self.status_label = QLabel("Chưa kết nối")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.uid_frame = QFrame()
        self.uid_frame.setFrameShape(QFrame.Shape.StyledPanel)
        uid_layout = QVBoxLayout(self.uid_frame)
        uid_layout.addWidget(QLabel("UID THẺ"))
        self.uid_label = QLabel("---")
        self.uid_label.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
        uid_layout.addWidget(self.uid_label)
        
        self.get_thermal_button = QPushButton("Lấy ảnh nhiệt")
        self.get_thermal_button.setEnabled(False)

        control_layout.addLayout(connection_layout)
        control_layout.addWidget(self.status_label)
        control_layout.addWidget(self.uid_frame)
        control_layout.addWidget(self.get_thermal_button)
        control_layout.addStretch()

        # --- Cột hiển thị nhiệt (phải) ---
        thermal_widget = QWidget()
        thermal_layout = QVBoxLayout(thermal_widget)
        thermal_title = QLabel("ẢNH NHIỆT 8x8")
        thermal_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thermal_title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.thermal_view = ThermalGridView()
        
        thermal_layout.addWidget(thermal_title)
        thermal_layout.addWidget(self.thermal_view, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.main_layout.addWidget(control_widget, 1)
        self.main_layout.addWidget(thermal_widget, 2)
        
        self.populate_ports()
        self.connect_button.clicked.connect(self.toggle_connection)
        self.get_thermal_button.clicked.connect(self.request_thermal_data)
        
    def populate_ports(self):
        self.port_combo.clear()
        for port in serial.tools.list_ports.comports():
            self.port_combo.addItem(port.device)
            
    def request_thermal_data(self):
        if self.serial_thread:
            self.serial_thread.send_command(0x10) # Gửi lệnh CMD_GET_THERMAL

    def toggle_connection(self):
        if self.serial_thread is None:
            port = self.port_combo.currentText()
            if not port: return
            self.connect_button.setText("Ngắt kết nối")
            self.port_combo.setEnabled(False)
            self.get_thermal_button.setEnabled(True)
            self.status_label.setText(f"Đang kết nối đến {port}...")

            self.serial_thread = SerialWorker(port)
            self.serial_thread.nfc_data_received.connect(lambda uid: self.uid_label.setText(uid))
            self.serial_thread.thermal_data_received.connect(self.thermal_view.update_grid)
            self.serial_thread.error_occurred.connect(self.handle_error)
            self.serial_thread.finished.connect(self.on_thread_finished)
            self.serial_thread.start()
        else:
            self.serial_thread.stop()
            self.serial_thread = None

    def handle_error(self, message):
        self.status_label.setText(f"Lỗi: {message}")
        self.on_thread_finished()

    def on_thread_finished(self):
        self.serial_thread = None
        self.status_label.setText("Đã ngắt kết nối")
        self.connect_button.setText("Kết nối")
        self.port_combo.setEnabled(True)
        self.get_thermal_button.setEnabled(False)

    def closeEvent(self, event):
        if self.serial_thread:
            self.serial_thread.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_stylesheet(app, theme='dark_teal.xml')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())