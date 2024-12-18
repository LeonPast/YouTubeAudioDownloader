import os
import sys
import threading
import yt_dlp
import subprocess
from metadata import add_metadata, convert_thumbnail


class Downloader:
    def __init__(self, download_folder, log_callback, progress_callback):
        """
        Класс, отвечающий за скачивание аудио с YouTube.
        :param download_folder: Папка для сохранения аудио.
        :param log_callback: Функция для логирования сообщений.
        :param progress_callback: Функция для обновления прогресса (принимает значение процента).
        """
        self.download_folder = download_folder
        os.makedirs(self.download_folder, exist_ok=True)
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.stop_event = threading.Event()
        self.thread = None

        # Определяем путь к ffmpeg
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            # Если запущено не из собранного .exe, используем локальный путь к bin
            base_path = os.path.join(os.path.dirname(__file__), 'bin')

        ffmpeg_path = os.path.join(base_path, 'ffmpeg.exe')
        ffprobe_path = os.path.join(base_path, 'ffprobe.exe')

        # Можно проверить доступность ffmpeg
        # Не обязательно, но полезно для отладки
        result = subprocess.run([ffmpeg_path, '-version'], capture_output=True, text=True)
        if result.returncode != 0:
            self.log_callback("Не удалось запустить ffmpeg. Проверьте, что файл ffmpeg.exe доступен.")
        else:
            self.log_callback(f"ffmpeg обнаружен: {result.stdout.splitlines()[0]}")

        # Если вы хотите передать ffmpeg в yt_dlp:
        # В опциях yt_dlp можно указать ffmpeg_location:
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path


    def start_download(self, url_list, completion_callback):
        """
        Запускает загрузку в отдельном потоке.
        :param url_list: Список ссылок для загрузки.
        :param completion_callback: Функция, вызываемая по завершении всех загрузок.
        """
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._download_all, args=(url_list, completion_callback))
        self.thread.start()

    def stop_download(self):
        """
        Останавливает процесс загрузки.
        """
        self.stop_event.set()

    def _download_all(self, url_list, completion_callback):
        total = len(url_list)
        for idx, url in enumerate(url_list):
            if self.stop_event.is_set():
                self.log_callback("Загрузка остановлена пользователем.")
                break
            try:
                self.log_callback(f"Обработка ссылки: {url}")
                result = self.download_audio(url)
                self.log_callback(result)
            except Exception as e:
                self.log_callback(f"Ошибка: {e}")

            progress = (idx + 1) / total * 100
            self.progress_callback(progress)

        completion_callback()

    def download_audio(self, url):
        """
        Скачивает аудиофайл с YouTube и внедряет метаданные, включая обложку.
        Возвращает строку с результатом.
        """
        if not self._ffmpeg_available():
            return "ffmpeg не найден. Установите ffmpeg для продолжения."

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(self.download_folder, '%(playlist_title)s', '%(title)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'ffmpeg_location': self.ffmpeg_path,  # Указываем путь к ffmpeg
            'writethumbnail': True,
            'no_color': True,
            'progress_hooks': [self._progress_hook],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)

            # Проверяем, что именно мы скачали - плейлист или одиночное видео
            if info_dict.get('_type') == 'playlist':
                # Для плейлиста info_dict содержит entries - список видео
                entries = info_dict.get('entries', [])
                result_messages = []
                for entry in entries:
                    msg = self._process_single_entry(entry)
                    result_messages.append(msg)
                return "\n".join(result_messages)
            else:
                # Одиночное видео
                return self._process_single_entry(info_dict)


    def _process_single_entry(self, info_dict):
        """
        Обрабатывает одну запись (один видео-трек), добавляя к нему обложку и метаданные.
        Используется и для одиночных видео, и для элементов плейлиста.
        """
        downloads = info_dict.get('requested_downloads', [])
        if not downloads:
            return "Не удалось определить скачанный файл для одной из записей."

        downloaded_path = downloads[0]['filepath']
        if not os.path.exists(downloaded_path):
            return f"Файл не был скачан: {downloaded_path}"

        # Определяем файл миниатюры
        base_name, _ = os.path.splitext(downloaded_path)
        webp_thumbnail = base_name + ".webp"
        thumbnail_path = None
        if os.path.exists(webp_thumbnail):
            thumbnail_path = convert_thumbnail(webp_thumbnail)

        # Добавляем метаданные
        meta_result = add_metadata(downloaded_path, info_dict, thumbnail_path)

        # Удаляем временные файлы thumbnail
        if thumbnail_path and os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)
        if os.path.exists(webp_thumbnail):
            os.remove(webp_thumbnail)

        return f"Готово: {downloaded_path}. {meta_result}"

    def _progress_hook(self, d):
        """
        Хук для прогресса, вызывается yt_dlp.
        """
        if d['status'] == 'downloading':
            p_str = d.get('_percent_str', '0%').strip()
            try:
                p_val = float(p_str.replace('%', ''))
            except ValueError:
                p_val = 0.0
            self.progress_callback(p_val)

    def _ffmpeg_available(self):
        """
        Простая проверка наличия ffmpeg.
        Можно улучшить, проверяя доступность в PATH.
        """
        from shutil import which
        return which("ffmpeg") is not None
