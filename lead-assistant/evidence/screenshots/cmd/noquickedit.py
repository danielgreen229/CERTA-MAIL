"""Отключает в текущем окне консоли выделение мышью (QuickEdit).

Случайный щелчок по окну переводит консоль Windows в режим «Выбрать» и приостанавливает
вывод программы. Для съёмки демонстрации это недопустимо: прогон должен идти сам.
"""

import ctypes

ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080

kernel32 = ctypes.windll.kernel32
handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
mode = ctypes.c_uint()
if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
    kernel32.SetConsoleMode(handle, (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS)
