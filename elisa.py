import os
import webbrowser
import whisper
import ollama
from gtts import gTTS
import sounddevice as sd
import soundfile as sf
import uuid
import logging
import pygame
import subprocess
import threading
from PIL import Image, ImageSequence
import time
from queue import Queue
import numpy as np
import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QPushButton, QTextEdit, QLineEdit, QScrollArea, QFrame)
from PyQt5.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal
from PyQt5.QtGui import QMovie, QPixmap, QIcon, QFont, QPalette, QColor, QTextCursor

# Configuración de logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Obtener la ruta del directorio del script
script_dir = os.path.dirname(os.path.abspath(__file__))

# Configuración de Whisper - Modelo pequeño para mejor rendimiento
whisper_model = whisper.load_model("small")

# Configuración de Ollama
model_name = "mistral"

# Nombre del asistente
nombre_asistente = "ELISA"

# Variable para almacenar el nombre del usuario
nombre_usuario = None

# Rutas relativas para archivos
temp_audio_path = os.path.join(script_dir, "grabacion.wav")
conversacion_path = os.path.join(script_dir, "conversacion.txt")
temp_audio_dir = os.path.join(script_dir, "temp_audio")
os.makedirs(temp_audio_dir, exist_ok=True)

# Configuración del avatar GIF
avatar_quieto_gif = os.path.join(script_dir, "assets", "avatar_quieto.gif")
avatar_hablando_gif = os.path.join(script_dir, "assets", "avatar_hablando.gif")

# Estados
class Estado:
    QUIETO = 0
    GRABANDO = 1
    HABLANDO = 2

class WorkerGrabacion(QThread):
    finished = pyqtSignal(str)
    update_status = pyqtSignal(str)
    
    def __init__(self, whisper_model, temp_audio_path):
        super().__init__()
        self.whisper_model = whisper_model
        self.temp_audio_path = temp_audio_path
        self._is_running = True
    
    def run(self):
        try:
            samplerate = 44100
            duration = 15
            
            self.update_status.emit(f"Grabando... {duration}s")
            audio = sd.rec(int(duration * samplerate), 
                         samplerate=samplerate, 
                         channels=1,
                         dtype='float32')
            
            for i in range(duration, 0, -1):
                if not self._is_running:
                    return
                self.update_status.emit(f"Grabando... {i}s")
                time.sleep(1)
            
            sd.wait()
            audio = self.mejorar_calidad_audio(audio, samplerate)
            sf.write(self.temp_audio_path, audio, samplerate)
            
            texto = self.transcribir_audio()
            self.finished.emit(texto)
        except Exception as e:
            logging.error(f"Error en grabación: {e}")
            self.finished.emit("")
    
    def mejorar_calidad_audio(self, audio, samplerate):
        try:
            if audio.ndim > 1:
                audio = np.mean(audio, axis=1)
            audio = audio / np.max(np.abs(audio))
            audio = np.convolve(audio, np.ones(5)/5, mode='same')
            return audio
        except Exception as e:
            logging.error(f"Error al mejorar audio: {e}")
            return audio
    
    def transcribir_audio(self):
        if not os.path.exists(self.temp_audio_path):
            logging.error(f"Archivo {self.temp_audio_path} no existe")
            return ""
        
        try:
            resultado = self.whisper_model.transcribe(
                self.temp_audio_path,
                language="spanish",
                task="transcribe",
                fp16=False,
                temperature=0.2,
                best_of=3,
                beam_size=5
            )
            
            texto = resultado["text"].strip()
            texto = self.limpiar_texto_transcrito(texto)
            return texto
        except Exception as e:
            logging.error(f"Error al transcribir: {e}")
            return ""
    
    def limpiar_texto_transcrito(self, texto):
        palabras_confusas = ["喝水", "thereel", "谢谢", "gracias", "thank you"]
        for palabra in palabras_confusas:
            texto = texto.replace(palabra, "")
        texto = ' '.join(texto.strip().split())
        return texto.capitalize()
    
    def stop(self):
        self._is_running = False
        self.terminate()

class WorkerHablar(QThread):
    finished = pyqtSignal()
    
    def __init__(self, texto, temp_audio_dir):
        super().__init__()
        self.texto = texto
        self.temp_audio_dir = temp_audio_dir
    
    def run(self):
        try:
            temp_tts_path = os.path.join(self.temp_audio_dir, f"respuesta_{uuid.uuid4()}.mp3")
            tts = gTTS(text=self.texto, lang="es", slow=False)
            tts.save(temp_tts_path)
            
            pygame.mixer.music.load(temp_tts_path)
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
                
        except Exception as e:
            logging.error(f"Error al reproducir audio: {e}")
        finally:
            try:
                os.remove(temp_tts_path)
            except:
                pass
            self.finished.emit()

class AsistenteVirtualGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.nombre_asistente = nombre_asistente
        self.nombre_usuario = nombre_usuario
        self.estado_actual = Estado.QUIETO
        self.conversacion = []
        
        # Inicializar pygame para audio
        pygame.init()
        pygame.mixer.init()
        
        self.setWindowTitle(f"Asistente Virtual {self.nombre_asistente}")
        self.setGeometry(100, 100, 1000, 700)
        self.setup_ui()
        
        # Mensaje inicial
        mensaje_inicial = f"{self.nombre_asistente}: ¡Hola! Soy {self.nombre_asistente}, tu asistente virtual. ¿Cómo te llamas?"
        self.agregar_mensaje(mensaje_inicial)
        self.hablar(mensaje_inicial.split(": ")[1])
    
    def setup_ui(self):
        # Widget central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Layout principal
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)
        
        # Columna izquierda (avatar)
        left_column = QVBoxLayout()
        left_column.setSpacing(15)
        
        # Avatar
        self.avatar_label = QLabel()
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.avatar_label.setFixedSize(300, 500)
        self.cargar_avatar(avatar_quieto_gif)
        
        # Estilo del avatar
        self.avatar_label.setStyleSheet("""
            QLabel {
                background-color: #eaeaea;
                border: 2px solid #d0d0d0;
                border-radius: 10px;
            }
        """)
        
        left_column.addWidget(self.avatar_label)
        
        # Botón de grabar
        self.grabar_button = QPushButton("Grabar Audio")
        self.grabar_button.setObjectName("grabarButton")
        self.grabar_button.setIcon(QIcon.fromTheme("microphone"))
        self.grabar_button.setIconSize(QSize(24, 24))
        self.grabar_button.setFixedHeight(40)
        self.grabar_button.clicked.connect(self.iniciar_grabacion)
        
        left_column.addWidget(self.grabar_button)
        left_column.addStretch()
        
        # Columna derecha (conversación)
        right_column = QVBoxLayout()
        right_column.setSpacing(15)
        
        # Título
        title_label = QLabel(f"Conversación con {self.nombre_asistente}")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: #333333;
                padding-bottom: 10px;
                border-bottom: 2px solid #4b8bbe;
            }
        """)
        right_column.addWidget(title_label)
        
        # Área de conversación
        self.conversacion_text = QTextEdit()
        self.conversacion_text.setReadOnly(True)
        self.conversacion_text.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 1px solid #d0d0d0;
                border-radius: 10px;
                padding: 15px;
                font-size: 14px;
                color: #333333;
            }
        """)
        
        # Configurar scroll
        scroll_area = QScrollArea()
        scroll_area.setWidget(self.conversacion_text)
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("border: none;")
        right_column.addWidget(scroll_area)
        
        # Entrada de texto
        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("Escribe tu mensaje aquí...")
        self.input_line.setStyleSheet("""
            QLineEdit {
                background-color: white;
                border: 1px solid #d0d0d0;
                border-radius: 10px;
                padding: 12px;
                font-size: 14px;
                color: #333333;
            }
        """)
        self.input_line.returnPressed.connect(self.enviar_mensaje)
        right_column.addWidget(self.input_line)
        
        # Botones inferiores
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        self.enviar_button = QPushButton("Enviar")
        self.enviar_button.setIcon(QIcon.fromTheme("mail-send"))
        self.enviar_button.clicked.connect(self.enviar_mensaje)
        button_layout.addWidget(self.enviar_button)
        
        self.limpiar_button = QPushButton("Limpiar")
        self.limpiar_button.setIcon(QIcon.fromTheme("edit-clear"))
        self.limpiar_button.clicked.connect(self.limpiar_conversacion)
        button_layout.addWidget(self.limpiar_button)
        
        self.cerrar_button = QPushButton("Cerrar")
        self.cerrar_button.setObjectName("cerrarButton")
        self.cerrar_button.setIcon(QIcon.fromTheme("window-close"))
        self.cerrar_button.clicked.connect(self.close)
        button_layout.addWidget(self.cerrar_button)
        
        right_column.addLayout(button_layout)
        
        # Añadir columnas al layout principal
        main_layout.addLayout(left_column, 30)
        main_layout.addLayout(right_column, 70)
        
        # Configurar estilo general
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
            }
            QPushButton {
                background-color: #4b8bbe;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 14px;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #6fa8dc;
            }
            QPushButton:pressed {
                background-color: #3a6a94;
            }
            #grabarButton {
                background-color: #2ecc71;
            }
            #grabarButton:hover {
                background-color: #27ae60;
            }
            #grabarButton:pressed {
                background-color: #219653;
            }
            #cerrarButton {
                background-color: #e74c3c;
            }
            #cerrarButton:hover {
                background-color: #c0392b;
            }
        """)
    
    def cargar_avatar(self, gif_path):
        """Carga el GIF del avatar en el QLabel."""
        if os.path.exists(gif_path):
            self.avatar_movie = QMovie(gif_path)
            self.avatar_movie.setScaledSize(QSize(300, 500))
            self.avatar_label.setMovie(self.avatar_movie)
            self.avatar_movie.start()
        else:
            # Avatar por defecto si no se encuentra el GIF
            pixmap = QPixmap(300, 500)
            pixmap.fill(QColor(234, 234, 234))
            self.avatar_label.setPixmap(pixmap)
    
    def cambiar_estado_avatar(self, estado):
        """Cambia el estado del avatar (quieto/hablando)."""
        if estado == Estado.QUIETO:
            self.cargar_avatar(avatar_quieto_gif)
        elif estado in (Estado.GRABANDO, Estado.HABLANDO):
            self.cargar_avatar(avatar_hablando_gif)
    
    def agregar_mensaje(self, mensaje):
        """Agrega un mensaje a la conversación."""
        self.conversacion.append(mensaje)
        self.guardar_conversacion(mensaje)
        
        # Formatear el mensaje con color diferente para el asistente/usuario
        cursor = self.conversacion_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        if mensaje.startswith(f"{self.nombre_asistente}:"):
            color = "#2c3e50"  # Azul oscuro para el asistente
            prefix = f"<b>{self.nombre_asistente}:</b> "
            texto = mensaje[len(f"{self.nombre_asistente}:"):].strip()
        else:
            color = "#27ae60"  # Verde para el usuario
            prefix = "<b>Tú:</b> "
            texto = mensaje[len("Tú:"):].strip() if mensaje.startswith("Tú:") else mensaje
        
        # Agregar separador si no es el primer mensaje
        if self.conversacion_text.toPlainText():
            cursor.insertHtml("<hr style='margin: 10px 0; border: 1px solid #eee;'>")
        
        # Insertar el mensaje formateado
        cursor.insertHtml(f"""
            <div style='color: {color}; margin: 5px 0;'>
                {prefix}{texto}
            </div>
        """)
        
        # Auto-scroll
        self.conversacion_text.verticalScrollBar().setValue(
            self.conversacion_text.verticalScrollBar().maximum())
    
    def guardar_conversacion(self, mensaje):
        """Guarda la conversación en un archivo de texto."""
        try:
            with open(conversacion_path, "a", encoding="utf-8") as archivo:
                archivo.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {mensaje}\n")
        except Exception as e:
            logging.error(f"Error al guardar conversación: {e}")
    
    def enviar_mensaje(self):
        """Envía el mensaje escrito por el usuario."""
        texto = self.input_line.text().strip()
        if texto:
            self.agregar_mensaje(f"Tú: {texto}")
            self.input_line.clear()
            
            # Procesar el mensaje y obtener respuesta
            respuesta = self.generar_respuesta(texto)
            self.agregar_mensaje(f"{self.nombre_asistente}: {respuesta}")
            self.hablar(respuesta)
            
            # Ejecutar comandos si es necesario
            self.ejecutar_comando(texto)
    
    def iniciar_grabacion(self):
        """Inicia el proceso de grabación de audio."""
        if hasattr(self, 'worker_grabacion') and self.worker_grabacion.isRunning():
            return
        
        self.cambiar_estado_avatar(Estado.GRABANDO)
        self.grabar_button.setEnabled(False)
        self.grabar_button.setText("Grabando...")
        
        self.worker_grabacion = WorkerGrabacion(whisper_model, temp_audio_path)
        self.worker_grabacion.finished.connect(self.finalizar_grabacion)
        self.worker_grabacion.update_status.connect(
            lambda msg: self.agregar_mensaje(f"{self.nombre_asistente}: {msg}"))
        self.worker_grabacion.start()
    
    def finalizar_grabacion(self, texto):
        """Finaliza el proceso de grabación y procesa el texto."""
        self.grabar_button.setEnabled(True)
        self.grabar_button.setText("Grabar Audio")
        self.cambiar_estado_avatar(Estado.QUIETO)
        
        if texto:
            self.agregar_mensaje(f"Tú: {texto}")
            
            # Generar y mostrar respuesta
            respuesta = self.generar_respuesta(texto)
            self.agregar_mensaje(f"{self.nombre_asistente}: {respuesta}")
            self.hablar(respuesta)
            
            # Ejecutar comandos si es necesario
            self.ejecutar_comando(texto)
    
    def generar_respuesta(self, texto):
        """Genera una respuesta usando Ollama."""
        texto_lower = texto.lower()
        
        # Detección de nombre
        if self.nombre_usuario is None:
            if "me llamo" in texto_lower:
                self.nombre_usuario = texto_lower.split("me llamo")[-1].strip().title()
            elif "mi nombre es" in texto_lower:
                self.nombre_usuario = texto_lower.split("mi nombre es")[-1].strip().title()
            elif "soy" in texto_lower:
                self.nombre_usuario = texto_lower.split("soy")[-1].strip().title()
            
            if self.nombre_usuario and len(self.nombre_usuario) > 1:
                respuesta = f"¡Mucho gusto, {self.nombre_usuario}! ¿En qué puedo ayudarte hoy?"
                logging.info(f"Nombre detectado: {self.nombre_usuario}")
                return respuesta
        
        # Generar respuesta normal
        prompt = (
            f"Eres {self.nombre_asistente}, un asistente virtual en español. "
            f"{f'El usuario {self.nombre_usuario} te dice:' if self.nombre_usuario else 'Usuario:'} {texto}\n"
            f"Responde de manera clara y concisa en español (máximo 50 palabras):"
        )
        
        try:
            respuesta = ollama.generate(
                model=model_name,
                prompt=prompt,
                options={"max_tokens": 50}
            )
            return respuesta["response"]
        except Exception as e:
            logging.error(f"Error al generar respuesta: {e}")
            return "Lo siento, no pude procesar tu solicitud."
    
    def hablar(self, texto):
        """Convierte el texto en voz usando gTTS."""
        self.cambiar_estado_avatar(Estado.HABLANDO)
        
        self.worker_hablar = WorkerHablar(texto, temp_audio_dir)
        self.worker_hablar.finished.connect(
            lambda: self.cambiar_estado_avatar(Estado.QUIETO))
        self.worker_hablar.start()
    
    def ejecutar_comando(self, texto):
        """Ejecuta comandos específicos."""
        texto = texto.lower()
        
        comandos = {
            "abrir chrome": lambda: subprocess.Popen("chrome.exe"),
            "abrir notepad": lambda: subprocess.Popen("notepad.exe"),
            "abrir calculadora": lambda: subprocess.Popen("calc.exe"),
            "ir a ": lambda url: webbrowser.open(f"https://{url}" if not url.startswith(("http", "www")) else url),
            "reproducir ": lambda cancion: webbrowser.open(f"https://www.youtube.com/results?search_query={cancion}")
        }
        
        for cmd, accion in comandos.items():
            if texto.startswith(cmd):
                try:
                    parametro = texto[len(cmd):].strip()
                    if parametro:
                        accion(parametro)
                    else:
                        accion()
                    return True
                except Exception as e:
                    logging.error(f"Error al ejecutar comando {cmd}: {e}")
        return False
    
    def limpiar_conversacion(self):
        """Limpia el área de conversación."""
        self.conversacion_text.clear()
        self.conversacion = []
    
    def closeEvent(self, event):
        """Maneja el cierre de la aplicación."""
        if hasattr(self, 'worker_grabacion') and self.worker_grabacion.isRunning():
            self.worker_grabacion.stop()
        
        if hasattr(self, 'worker_hablar') and self.worker_hablar.isRunning():
            self.worker_hablar.terminate()
        
        pygame.quit()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Configurar fuente global
    font = QFont("Arial", 12)
    app.setFont(font)
    
    # Configurar paleta de colores
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(245, 245, 245))
    palette.setColor(QPalette.WindowText, QColor(51, 51, 51))
    palette.setColor(QPalette.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.AlternateBase, QColor(240, 240, 240))
    palette.setColor(QPalette.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ToolTipText, QColor(51, 51, 51))
    palette.setColor(QPalette.Text, QColor(51, 51, 51))
    palette.setColor(QPalette.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ButtonText, QColor(51, 51, 51))
    palette.setColor(QPalette.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.Highlight, QColor(75, 139, 190))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)
    
    window = AsistenteVirtualGUI()
    window.show()
    sys.exit(app.exec_())
