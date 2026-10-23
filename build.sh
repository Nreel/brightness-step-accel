#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv --system-site-packages .venv
    .venv/bin/pip install pyinstaller
fi

if [ ! -f "build_tools/appimagetool" ]; then
    echo "Downloading appimagetool..."
    mkdir -p build_tools
    curl -L -o build_tools/appimagetool \
        https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x build_tools/appimagetool
fi

echo "Building standalone binary..."
.venv/bin/pyinstaller --onefile --windowed --name brightness-step-accel app.py

echo "Building AppImage..."
rm -rf AppDir
mkdir -p \
    AppDir/usr/bin \
    AppDir/usr/share/applications \
    AppDir/usr/share/icons/hicolor/scalable/apps \
    AppDir/usr/share/metainfo

cp dist/brightness-step-accel AppDir/usr/bin/

# appimagetool expects the desktop file and icon in the AppDir root.
cp brightness-step-accel.desktop AppDir/
cp brightness-step-accel.desktop AppDir/usr/share/applications/
cp brightness-step-accel.svg AppDir/
cp brightness-step-accel.svg AppDir/usr/share/icons/hicolor/scalable/apps/

cat > AppDir/AppRun << 'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
exec "${HERE}/usr/bin/brightness-step-accel" "$@"
EOF
chmod +x AppDir/AppRun

cat > AppDir/usr/share/metainfo/org.github.brightness_step_accel.appdata.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>org.github.brightness_step_accel</id>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <name>Brightness Step Accelerator</name>
  <summary>Increase brightness step size when tapping brightness keys rapidly</summary>
  <description>
    <p>Brightness Step Accelerator is a small GTK4 application for Linux that makes the brightness step grow when the brightness keys are tapped rapidly, similar to the Windows behaviour.</p>
  </description>
  <categories>
    <category>Utility</category>
  </categories>
  <url type="homepage">https://github.com/nreel/brightness-step-accel</url>
  <launchable type="desktop-id">brightness-step-accel.desktop</launchable>
  <content_rating type="oars-1.1"/>
  <developer id="org.github">
    <name>Brightness Step Accelerator Contributors</name>
  </developer>
</component>
EOF

chmod +x build_tools/appimagetool
ARCH=x86_64 ./build_tools/appimagetool AppDir dist/brightness-step-accel.AppImage

echo ""
echo "Build complete:"
echo "  Binary:   dist/brightness-step-accel"
echo "  AppImage: dist/brightness-step-accel.AppImage"
