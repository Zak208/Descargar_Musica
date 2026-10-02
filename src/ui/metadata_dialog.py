import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog
)
from services.metadata_service import MetadataService


from ui.dialogs import show_message
from ui.overlay import InlineDialog

class MetadataDialog(InlineDialog):
    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.new_cover_path = None
        self.setWindowTitle("Editar Información y Carátula")
        self.setFixedSize(480, 420)
        self.init_ui()
        self.load_current_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QLabel("Editar Información del Audio")
        header.setObjectName("DialogHeader")
        layout.addWidget(header)

        # Contenedor superior con carátula y campos
        top_box = QHBoxLayout()
        top_box.setSpacing(20)

        # Carátula
        cover_col = QVBoxLayout()
        cover_col.setAlignment(Qt.AlignCenter)
        cover_col.setSpacing(8)

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(110, 110)
        self.cover_label.setStyleSheet("background-color: #242424; border-radius: 8px; border: 1px solid #383838;")
        self.cover_label.setScaledContents(True)
        cover_col.addWidget(self.cover_label)

        self.btn_change_cover = QPushButton("Cambiar foto...")
        self.btn_change_cover.setStyleSheet("font-size: 11px; padding: 6px 12px; border-radius: 6px;")
        self.btn_change_cover.setCursor(Qt.PointingHandCursor)
        self.btn_change_cover.clicked.connect(self.select_new_cover)
        cover_col.addWidget(self.btn_change_cover)

        top_box.addLayout(cover_col)

        # Campos de texto
        fields_col = QVBoxLayout()
        fields_col.setSpacing(10)

        fields_col.addWidget(QLabel("Título:"))
        self.input_title = QLineEdit()
        self.input_title.setObjectName("DialogInput")
        fields_col.addWidget(self.input_title)

        fields_col.addWidget(QLabel("Artista:"))
        self.input_artist = QLineEdit()
        self.input_artist.setObjectName("DialogInput")
        fields_col.addWidget(self.input_artist)

        fields_col.addWidget(QLabel("Álbum:"))
        self.input_album = QLineEdit()
        self.input_album.setObjectName("DialogInput")
        fields_col.addWidget(self.input_album)

        top_box.addLayout(fields_col, stretch=1)
        layout.addLayout(top_box)

        layout.addStretch()

        # Botones de acción inferiores
        btn_box = QHBoxLayout()
        btn_box.setSpacing(12)
        btn_box.addStretch()

        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setCursor(Qt.PointingHandCursor)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Guardar Cambios")
        self.btn_save.setStyleSheet("background-color: #1ED760; color: #000000; font-weight: bold;")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self.save_metadata)
        btn_box.addWidget(self.btn_save)

        layout.addLayout(btn_box)

    def load_current_data(self):
        data = MetadataService.read_metadata(self.file_path)
        base_name = os.path.splitext(os.path.basename(self.file_path))[0]

        self.input_title.setText(data.get("title") or base_name)
        self.input_artist.setText(data.get("artist") or "Artista Desconocido")
        self.input_album.setText(data.get("album") or "")

        if data.get("has_cover") and data.get("cover_data"):
            img = QImage()
            if img.loadFromData(data["cover_data"]):
                pix = QPixmap.fromImage(img).scaled(110, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.cover_label.setPixmap(pix)
        else:
            self.cover_label.setText("Sin carátula")
            self.cover_label.setAlignment(Qt.AlignCenter)

    def select_new_cover(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar carátula", "", "Imágenes (*.jpg *.jpeg *.png)"
        )
        if path and os.path.exists(path):
            self.new_cover_path = path
            pix = QPixmap(path).scaled(110, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.cover_label.setPixmap(pix)

    def save_metadata(self):
        title = self.input_title.text().strip()
        artist = self.input_artist.text().strip()
        album = self.input_album.text().strip()

        if not title:
            show_message(self, "Falta el título", "La canción necesita un título.")
            return

        success = MetadataService.update_metadata(
            file_path=self.file_path,
            title=title,
            artist=artist,
            album=album,
            new_cover_path=self.new_cover_path
        )

        if success:
            show_message(self, "Guardado", "Los cambios se han guardado.")
            self.accept()
        else:
            show_message(self, "No se pudo guardar", "No se pudieron guardar los cambios de este archivo.")
