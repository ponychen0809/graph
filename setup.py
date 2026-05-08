import pybind11
from setuptools import setup, Extension

ext_modules = [
    Extension(
        "graph_cpp_core",                     # 編譯出來的模組名稱
        ["graph_solver.cpp"],                 # 你的 C++ 原始檔
        include_dirs=[pybind11.get_include()],
        language='c++',
        # 開啟最高級別的最佳化 (讓運算速度飛起來)
        extra_compile_args=['-O3'] # 如果是 Windows MSVC，請改成 ['/O2']
    ),
]

setup(
    name="graph_cpp_core",
    ext_modules=ext_modules,
)