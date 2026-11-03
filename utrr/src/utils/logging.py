"""日志与输出重定向。"""

from __future__ import annotations

import logging
import sys


class Logger:
	"""同时输出到控制台与日志文件的轻量日志器。"""

	def __init__(self, level: str = "INFO", log_file: str | None = None):
		self.level = getattr(logging, level.upper(), 20)
		self.log_file = log_file
		self._file = None
		if log_file:
			self._file = open(log_file, "w", encoding="utf-8")

	def _log(self, level_name: str, message: str) -> None:
		line = f"[{level_name}] {message}"
		print(line, file=sys.stdout)
		if self._file:
			self._file.write(line + "\n")
			self._file.flush()

	def debug(self, message: str) -> None:
		if self.level <= 10:
			self._log("DEBUG", message)

	def info(self, message: str) -> None:
		if self.level <= 20:
			self._log("INFO", message)

	def warning(self, message: str) -> None:
		if self.level <= 30:
			self._log("WARNING", message)

	def error(self, message: str) -> None:
		if self.level <= 40:
			self._log("ERROR", message)

	def close(self) -> None:
		if self._file:
			self._file.close()
			self._file = None


class Tee:
	"""把 stdout 同时写入控制台与文件，用于把整段实验输出收进 experiment.log。"""

	def __init__(self, filepath: str):
		self._file = open(filepath, "w", encoding="utf-8")
		self._stdout = sys.stdout

	def write(self, data: str) -> None:
		self._stdout.write(data)
		self._file.write(data)
		self._file.flush()

	def flush(self) -> None:
		self._stdout.flush()
		self._file.flush()

	def close(self) -> None:
		self._file.close()
		sys.stdout = self._stdout
