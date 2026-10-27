# Maintainer: Your Name <your.email@example.com>
pkgname=fn-keys-accel
pkgver=0.1.0
pkgrel=1
pkgdesc="Increase brightness and volume step size when tapping keys rapidly"
arch=('any')
url="https://github.com/nreel/fn-keys-accel"
license=('MIT')
depends=('python' 'python-evdev' 'python-gobject' 'gtk4')
optdepends=('brightnessctl: for brightness control without root')
makedepends=('git')
source=("$pkgname-$pkgver.tar.gz::https://github.com/nreel/fn-keys-accel/archive/v$pkgver.tar.gz")
sha256sums=('SKIP')

package() {
    cd "$srcdir/$pkgname-$pkgver"

    # Install the main Python script as an executable
    install -Dm755 app.py "$pkgdir/usr/bin/$pkgname"

    # Install the desktop entry
    install -Dm644 "$pkgname.desktop" "$pkgdir/usr/share/applications/$pkgname.desktop"

    # Install the icon
    install -Dm644 "$pkgname.svg" "$pkgdir/usr/share/icons/hicolor/scalable/apps/$pkgname.svg"
}
