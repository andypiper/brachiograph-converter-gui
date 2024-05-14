# TODO: better help info / commenting
# TODO: handle image sizing
# TODO: test on Linux and Windows
# TODO: figure out a way to handle SVG
# TODO: other optimisations e.g. reduce paths, threading
# TODO: send print instruction?

import sys
import subprocess
import os
import json
from pathlib import Path

from PySide6 import QtWidgets, QtGui, QtCore
from PySide6.QtWidgets import QApplication, QMainWindow
import paramiko
import cairosvg

from linedraw import image_to_json

SIZE_LIMIT = 3 * 1024 * 1024  # 3 MB
DEFAULT_SETTINGS = {
    "draw_contours": 2,
    "draw_hatch": 16,
    "repeat_contours": 0,
    "sftp_hostname": "",
    "sftp_user": "",
    "sftp_password": "",
    "sftp_directory": "",
}
IMAGE_EXTENSIONS = "Images (*.jpg *.jpeg *.png *.tif *.tiff *.webp)"
JSON_EXTENSION = "JSON files (*.json)"
CONFIG_FILE = Path.home() / ".brachiograph_converter.json"


class SFTPSettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SFTP Settings")

        self.sftp_hostname_label = QtWidgets.QLabel("SFTP Hostname:")
        self.sftp_hostname_input = QtWidgets.QLineEdit()
        self.sftp_user_label = QtWidgets.QLabel("SFTP User:")
        self.sftp_user_input = QtWidgets.QLineEdit()
        self.sftp_password_label = QtWidgets.QLabel("SFTP Password:")
        self.sftp_password_input = QtWidgets.QLineEdit()
        self.sftp_password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self.sftp_directory_label = QtWidgets.QLabel("SFTP Directory:")
        self.sftp_directory_input = QtWidgets.QLineEdit()

        layout = QtWidgets.QFormLayout()
        layout.addRow(self.sftp_hostname_label, self.sftp_hostname_input)
        layout.addRow(self.sftp_user_label, self.sftp_user_input)
        layout.addRow(self.sftp_password_label, self.sftp_password_input)
        layout.addRow(self.sftp_directory_label, self.sftp_directory_input)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout.addWidget(button_box)
        self.setLayout(layout)


class BrachiographConverterMainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BrachioGraph Image Converter")

        self.central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.central_widget)

        self.setupUI()

        # Set the application icon and name
        app_icon = QtGui.QIcon((str(Path("ui") / "icon.png")))
        QtWidgets.QApplication.setWindowIcon(app_icon)
        QtWidgets.QApplication.setApplicationName("BrachioGraph Image Converter")

        # Load settings from configuration file
        self.load_settings()

        # Restore window geometry and state
        self.read_settings()

    def setupUI(self):
        self.content_image_label = QtWidgets.QLabel("Image:")
        self.content_image_input = QtWidgets.QLineEdit()
        self.content_image_button = QtWidgets.QPushButton("Browse")

        self.draw_contours_label = QtWidgets.QLabel("Contours:")
        self.draw_contours_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.draw_contours_slider.setRange(0, 10)
        self.draw_contours_slider.setToolTip(
            "Default is 2, try values between 0.5 and 4. Smaller = more detail."
        )
        self.draw_contours_value_label = QtWidgets.QLabel()

        self.draw_hatch_label = QtWidgets.QLabel("Hatch:")
        self.draw_hatch_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.draw_hatch_slider.setRange(1, 100)
        self.draw_hatch_slider.setToolTip(
            "Space between hatching. Default is 16, try values between 8 and 16. Smaller = more detail."
        )
        self.draw_hatch_value_label = QtWidgets.QLabel()

        self.repeat_contours_label = QtWidgets.QLabel("Repeat Contours:")
        self.repeat_contours_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.repeat_contours_slider.setRange(0, 10)
        self.repeat_contours_slider.setToolTip(
            "Number of times to repeat outer lines, so the edges of the final image stand out. Default is 0."
        )
        self.repeat_contours_value_label = QtWidgets.QLabel()

        self.generate_button = QtWidgets.QPushButton("Generate")
        self.upload_button = QtWidgets.QPushButton("Upload Files")
        self.quit_button = QtWidgets.QPushButton("Quit")
        self.sftp_settings_button = QtWidgets.QPushButton("SFTP Settings")
        self.view_files_button = QtWidgets.QPushButton("View Files")

        self.image_widget = QtWidgets.QLabel()
        self.image_widget.setStyleSheet(
            "background-color: white; border: 1px solid gray;"
        )
        self.image_widget.setAlignment(QtCore.Qt.AlignCenter)
        self.image_widget.setMinimumSize(512, 512)

        self.json_file_label = QtWidgets.QLabel("JSON File:")
        self.json_file_input = QtWidgets.QLineEdit()
        self.json_file_button = QtWidgets.QPushButton("Browse")

        self.convert_label = QtWidgets.QLabel("<b>Convert Image to JSON</b>")
        self.convert_label.setAlignment(QtCore.Qt.AlignCenter)
        self.upload_label = QtWidgets.QLabel("<b>Upload to BrachioGraph</b>")
        self.upload_label.setAlignment(QtCore.Qt.AlignCenter)

        content_layout = QtWidgets.QHBoxLayout()
        content_layout.addWidget(self.content_image_input, stretch=1)
        content_layout.addWidget(self.content_image_button)

        draw_contours_layout = QtWidgets.QHBoxLayout()
        draw_contours_layout.addWidget(self.draw_contours_slider, stretch=1)
        draw_contours_layout.addWidget(self.draw_contours_value_label)

        draw_hatch_layout = QtWidgets.QHBoxLayout()
        draw_hatch_layout.addWidget(self.draw_hatch_slider, stretch=1)
        draw_hatch_layout.addWidget(self.draw_hatch_value_label)

        repeat_contours_layout = QtWidgets.QHBoxLayout()
        repeat_contours_layout.addWidget(self.repeat_contours_slider, stretch=1)
        repeat_contours_layout.addWidget(self.repeat_contours_value_label)

        json_file_layout = QtWidgets.QHBoxLayout()
        json_file_layout.addWidget(self.json_file_input, stretch=1)
        json_file_layout.addWidget(self.json_file_button)

        upload_button_layout = QtWidgets.QHBoxLayout()
        upload_button_layout.addWidget(self.upload_button)

        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)

        separator2 = QtWidgets.QFrame()
        separator2.setFrameShape(QtWidgets.QFrame.HLine)
        separator2.setFrameShadow(QtWidgets.QFrame.Sunken)

        separator3 = QtWidgets.QFrame()
        separator3.setFrameShape(QtWidgets.QFrame.HLine)
        separator3.setFrameShadow(QtWidgets.QFrame.Sunken)

        file_management_layout = QtWidgets.QHBoxLayout()
        file_management_layout.addWidget(self.view_files_button)
        file_management_layout.addWidget(self.sftp_settings_button)

        left_layout = QtWidgets.QVBoxLayout()
        left_layout.addWidget(self.convert_label)
        left_layout.addWidget(self.content_image_label)
        left_layout.addLayout(content_layout)
        left_layout.addWidget(self.draw_contours_label)
        left_layout.addLayout(draw_contours_layout)
        left_layout.addWidget(self.draw_hatch_label)
        left_layout.addLayout(draw_hatch_layout)
        left_layout.addWidget(self.repeat_contours_label)
        left_layout.addLayout(repeat_contours_layout)
        left_layout.addWidget(self.generate_button)
        left_layout.addSpacing(20)

        left_layout.addWidget(separator)
        left_layout.addSpacing(20)
        left_layout.addWidget(self.upload_label)
        left_layout.addWidget(self.json_file_label)
        left_layout.addLayout(json_file_layout)
        left_layout.addLayout(upload_button_layout)
        left_layout.addSpacing(20)

        left_layout.addWidget(separator3)
        left_layout.addSpacing(20)
        left_layout.addLayout(file_management_layout)
        left_layout.addSpacing(20)

        left_layout.addWidget(separator2)
        left_layout.addSpacing(20)
        left_layout.addWidget(self.quit_button)
        left_layout.addStretch()
        left_layout.setSpacing(10)
        left_layout.setContentsMargins(10, 10, 10, 10)

        right_layout = QtWidgets.QVBoxLayout()
        right_layout.addWidget(self.image_widget)
        right_layout.addStretch()
        self.set_picture(Path("ui") / "blank.png")

        main_layout = QtWidgets.QHBoxLayout()
        main_layout.addLayout(left_layout, stretch=1)
        main_layout.addSpacing(20)
        main_layout.addLayout(right_layout, stretch=2)

        self.central_widget.setLayout(main_layout)

        # Connect signals and slots
        self.content_image_button.clicked.connect(self.browse_content_image)
        self.generate_button.clicked.connect(self.generate_json)
        self.upload_button.clicked.connect(self.upload_files)
        self.quit_button.clicked.connect(self.close)
        self.draw_contours_slider.valueChanged.connect(self.update_draw_contours_value)
        self.draw_hatch_slider.valueChanged.connect(self.update_draw_hatch_value)
        self.repeat_contours_slider.valueChanged.connect(
            self.update_repeat_contours_value
        )
        self.json_file_button.clicked.connect(self.browse_json_file)
        self.sftp_settings_button.clicked.connect(self.show_sftp_settings)
        self.view_files_button.clicked.connect(self.open_images_directory)

        # Load settings from configuration file
        self.load_settings()

        # Ensure labels are updated with their initial slider values
        self.update_draw_contours_value(self.draw_contours_slider.value())
        self.update_draw_hatch_value(self.draw_hatch_slider.value())
        self.update_repeat_contours_value(self.repeat_contours_slider.value())

    def browse_content_image(self):
        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Image", str(Path.home()), IMAGE_EXTENSIONS
        )
        if file_name is not None:
            self.content_image_input.setText(file_name)

    def generate_json(self):
        print("Begin JSON generation")

        image_file = self.content_image_input.text()

        if not image_file:
            QtWidgets.QMessageBox.critical(
                self, "Image Not Selected", "Please select an image file to convert."
            )
            return

        # Check file size
        file_size = os.path.getsize(image_file)
        if file_size > SIZE_LIMIT:
            QtWidgets.QMessageBox.warning(
                self,
                "File Size Warning",
                "The selected image file is too large. Please resize it to a smaller size and try again.",
            )
            return

        # Convert
        image_to_json(
            image_file,
            draw_contours=int(self.draw_contours_slider.value()),
            draw_hatch=int(self.draw_hatch_slider.value()),
            repeat_contours=int(self.repeat_contours_slider.value()),
        )

        # Display
        input_svg = Path("images") / f"{Path(image_file).stem}.svg"
        output_png = Path("temp") / "converted.png"

        with open(str(input_svg), "r") as svg_file:
            with open(str(output_png), "wb") as png_file:
                cairosvg.svg2png(
                    file_obj=svg_file,
                    write_to=png_file,
                    parent_width=512,
                    parent_height=512,
                )

        self.set_picture(output_png)

    def set_picture(self, pngfile):
        pixmap = QtGui.QPixmap(str(pngfile))

        self.image_widget.setPixmap(
            pixmap.scaled(
                self.image_widget.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
        )

    def browse_json_file(self):
        images_directory = Path("images")
        if not images_directory.exists():
            images_directory.mkdir(parents=True)

        file_name, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select JSON File", str(images_directory), JSON_EXTENSION
        )
        if file_name:
            self.json_file_input.setText(file_name)

    def upload_files(self):
        settings = self.load_settings()
        hostname = settings.get("sftp_hostname", "")
        username = settings.get("sftp_user", "")
        password = settings.get("sftp_password", "")
        remote_directory = settings.get("sftp_directory", "")
        json_file = self.json_file_input.text()

        if not json_file:
            QtWidgets.QMessageBox.critical(
                self, "JSON File Not Selected", "Please select a JSON file to upload."
            )
            return

        if not hostname or not username or not password or not remote_directory:
            QtWidgets.QMessageBox.critical(
                self,
                "SFTP Configuration Missing",
                "Please configure the SFTP connection settings before uploading a file.\n\n"
                "To set the configuration, click on the 'SFTP Settings' button and provide the required information.",
            )
            return

        print(f"Begin SFTP upload to {hostname}")

        try:
            with paramiko.Transport((hostname, 22)) as transport:
                transport.connect(username=username, password=password)
                with paramiko.SFTPClient.from_transport(transport) as sftp_client:
                    print("Connection successfully established...")

                    remote_file_path = Path(remote_directory) / Path(json_file).name
                    sftp_client.put(json_file, str(remote_file_path))

            QtWidgets.QMessageBox.information(
                self, "Upload Completed", "File uploaded successfully."
            )
        except paramiko.AuthenticationException:
            QtWidgets.QMessageBox.critical(
                self,
                "Authentication Error",
                "Authentication failed. Please check your credentials.",
            )
        except Exception as exception:
            QtWidgets.QMessageBox.critical(
                self, "Error", f"An error occurred: {exception}"
            )

    def open_images_directory(self):
        images_directory = Path("images")
        if not images_directory.exists():
            images_directory.mkdir(parents=True)

        print(f"Opening directory: {images_directory}")

        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(images_directory)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(images_directory)])
            else:
                subprocess.Popen(["xdg-open", str(images_directory)])
        except Exception as exception:
            print(f"Error opening directory: {exception}")

    def update_draw_contours_value(self, value):
        self.draw_contours_value_label.setText(f"{value}")

    def update_draw_hatch_value(self, value):
        self.draw_hatch_value_label.setText(f"{value}")

    def update_repeat_contours_value(self, value):
        self.repeat_contours_value_label.setText(f"{value}")

    def show_sftp_settings(self):
        settings_dialog = SFTPSettingsDialog(self)
        settings = self.load_settings()
        settings_dialog.sftp_hostname_input.setText(settings.get("sftp_hostname", ""))
        settings_dialog.sftp_user_input.setText(settings.get("sftp_user", ""))
        settings_dialog.sftp_password_input.setText(settings.get("sftp_password", ""))
        settings_dialog.sftp_directory_input.setText(settings.get("sftp_directory", ""))

        if settings_dialog.exec() == QtWidgets.QDialog.Accepted:
            settings["sftp_hostname"] = settings_dialog.sftp_hostname_input.text()
            settings["sftp_user"] = settings_dialog.sftp_user_input.text()
            settings["sftp_password"] = settings_dialog.sftp_password_input.text()
            settings["sftp_directory"] = settings_dialog.sftp_directory_input.text()
            self.save_settings(settings)

    def load_settings(self):
        config_file = CONFIG_FILE

        if os.path.exists(config_file):
            with open(config_file, "r") as config:
                settings = json.load(config)
        else:
            settings = DEFAULT_SETTINGS
            self.save_settings(settings)

        self.draw_contours_slider.setValue(settings.get("draw_contours", 2))
        self.draw_hatch_slider.setValue(settings.get("draw_hatch", 16))
        self.repeat_contours_slider.setValue(settings.get("repeat_contours", 0))

        return settings

    def save_settings(self, settings):
        config_file = CONFIG_FILE

        with open(config_file, "w") as config:
            json.dump(settings, config)

    def closeEvent(self, event):
        self.write_settings()
        super().closeEvent(event)

    def read_settings(self):
        settings = QtCore.QSettings("uk.andypiper", "BrachioGUI")
        geometry = settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        window_state = settings.value("windowState")
        if window_state is not None:
            self.restoreState(window_state)

    def write_settings(self):
        settings = QtCore.QSettings("uk.andypiper", "BrachioGUI")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BrachiographConverterMainWindow()
    window.show()
    sys.exit(app.exec())
