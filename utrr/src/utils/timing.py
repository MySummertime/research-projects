"""计时工具：同时记录墙钟时间与进程 CPU 时间。"""

from __future__ import annotations

import time


class Timer:
	"""记录墙钟时间与 CPU 时间。"""

	def __init__(self):
		self._start_wall = 0.0
		self._start_cpu = 0.0
		self._elapsed_wall = 0.0
		self._elapsed_cpu = 0.0

	def start(self) -> "Timer":
		self._start_wall = time.perf_counter()
		self._start_cpu = time.process_time()
		return self

	def stop(self) -> tuple:
		"""停止计时并返回 (墙钟耗时, CPU 耗时)。"""
		self._elapsed_wall = time.perf_counter() - self._start_wall
		self._elapsed_cpu = time.process_time() - self._start_cpu
		return self._elapsed_wall, self._elapsed_cpu

	@property
	def elapsed_wall(self) -> float:
		return self._elapsed_wall

	@property
	def elapsed_cpu(self) -> float:
		return self._elapsed_cpu
