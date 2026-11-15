# -*- coding: utf-8 -*-
"""PyInstaller 打包脚本：python build.py
   产物 dist/AppLauncher/（onedir：热启动快、杀软误报少）
   打包后可运行 `AppLauncher.exe --autostart` 写入开机自启（指向 exe 本体）"""
import os
import subprocess
import sys

def main():
    root = os.path.dirname(os.path.abspath(__file__))
    import importlib.util
    if importlib.util.find_spec('PyInstaller') is None:
        print('缺少 pyinstaller：pip install pyinstaller>=6')
        return 1
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--clean',
        '--noconsole', '--onedir',
        '--name', 'AppLauncher',
        # 精简体积：排除用不到的模块
        '--exclude-module', 'tkinter',
        '--exclude-module', 'matplotlib',
        '--exclude-module', 'numpy',
        '--exclude-module', 'IPython',
        # QML 背景层资源（AL_QML=1 时加载）
        '--add-data', os.path.join(root, 'background.qml') + os.pathsep + '.',
        os.path.join(root, 'launcher.py'),
    ]
    print(' '.join(cmd))
    # 语法检查（含 scan.py，防止 CI/compileall 漏覆盖）
    import py_compile
    for f in ('launcher.py', 'scan.py', 'store.py', 'theme.py'):
        py_compile.compile(os.path.join(root, f), doraise=True)
    print('语法检查通过')
    subprocess.check_call(cmd, cwd=root)
    out = os.path.join(root, 'dist', 'AppLauncher')
    print()
    print('打包完成:', out)
    print('后续: 运行 AppLauncher.exe；--autostart 写开机自启；--uninstall 卸载')
    return 0

if __name__ == '__main__':
    sys.exit(main())
