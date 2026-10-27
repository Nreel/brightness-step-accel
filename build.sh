#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -d ".venv" ] && ! .venv/bin/pip --version >/dev/null 2>&1; then
    echo "Existing virtual environment is broken; recreating..."
    rm -rf .venv
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv --system-site-packages .venv
fi

echo "Installing Python build dependencies..."
.venv/bin/python3 -m pip install pyinstaller -r requirements.txt

if [ ! -f "build_tools/appimagetool" ]; then
    echo "Downloading appimagetool..."
    mkdir -p build_tools
    curl -L -o build_tools/appimagetool \
        https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x build_tools/appimagetool
fi

echo "Building standalone binary..."
.venv/bin/python3 -m PyInstaller --onefile --windowed --name fn-keys-accel app.py

echo "Building AppImage..."
rm -rf AppDir
mkdir -p \
    AppDir/usr/bin \
    AppDir/usr/share/applications \
    AppDir/usr/share/icons/hicolor/scalable/apps \
    AppDir/usr/share/metainfo

cp dist/fn-keys-accel AppDir/usr/bin/

# appimagetool expects the desktop file and icon in the AppDir root.
cp fn-keys-accel.desktop AppDir/
cp fn-keys-accel.desktop AppDir/usr/share/applications/
cp fn-keys-accel.svg AppDir/
cp fn-keys-accel.svg AppDir/usr/share/icons/hicolor/scalable/apps/

cat > AppDir/AppRun << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "${HERE}/usr/bin/fn-keys-accel" "$@"
EOF
chmod +x AppDir/AppRun

cat > AppDir/usr/share/metainfo/org.github.fn_keys_accel.appdata.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.github.fn_keys_accel</id>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <name>Fn Keys Accel</name>
  <summary>Increase brightness step size when tapping brightness keys rapidly</summary>
  <description>
    <p>Fn Keys Accel is a small GTK4 application for Linux that makes the brightness step grow when the brightness keys are tapped rapidly, similar to the Windows behaviour.</p>
  </description>
  <categories>
    <category>Utility</category>
  </categories>
  <url type="homepage">https://github.com/nreel/fn-keys-accel</url>
  <launchable type="desktop-id">fn-keys-accel.desktop</launchable>
  <content_rating type="oars-1.1"/>
  <developer id="org.github">
    <name>Fn Keys Accel Contributors</name>
  </developer>
</component>
EOF

chmod +x build_tools/appimagetool
ARCH=x86_64 ./build_tools/appimagetool AppDir dist/fn-keys-accel.AppImage

echo ""
echo "Build complete:"
echo "  Binary:   dist/fn-keys-accel"
echo "  AppImage: dist/fn-keys-accel.AppImage"
