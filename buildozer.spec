[app]
# (str) Title of your application
title = Labio

# (str) Package name
package.name = labio

# (str) Package domain (needed for android/ios packaging)
package.domain = org.labio

# (str) Source code where the main.py lives
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,json,svg

# (str) Application versioning (method 1)
version = 0.1

# (list) Application requirements
# ОБЯЗАТЕЛЬНО: добавьте requests (для API) и websocket-client (для чата)
requirements = python3,kivy,requests,websocket-client

# (str) Supported orientations (valid ones are: landscape, portrait, portrait-upside-down, landscape-left, landscape-right)
orientation = portrait

# (list) Permissions
# ОБЯЗАТЕЛЬНО: Разрешение на интернет
android.permissions = INTERNET

# (str) Android API to use (31-33 is optimal for now)
android.api = 31

# (str) Android NDK version to use
android.ndk = 25b

# (str) Android entry point, default is to use Main (will generate a Main.txt with the class name)
android.entrypoint = org.kivy.android.PythonActivity

# (list) The Android archs to build for.
android.archs = arm64-v8a, armeabi-v7a

# (bool) Use p4a build_dir
p4a.use_build_dir = True

[buildozer]
# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
wa
rn_on_root = 1
