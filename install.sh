#!/bin/sh
# Install or update Sports CLI with one command:
#   curl -fsSL https://raw.githubusercontent.com/osiddiki/sports-cli/main/install.sh | sh
# Options: --ppv also sets up Node.js and the PPV resolver; --yes skips the confirmation.
set -eu

REPO=osiddiki/sports-cli
ARCHIVE=${SPORTS_CLI_ARCHIVE:-https://github.com/$REPO/archive/refs/heads/main.tar.gz}
APP=${SPORTS_CLI_HOME:-$HOME/.local/share/sports-cli}
BIN=$HOME/.local/bin
PPV=0; YES=0
for arg in "$@"; do
  case $arg in
    --ppv) PPV=1 ;;
    --yes) YES=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nSetup stopped: %s\n' "$*" >&2; exit 1; }
run() { if [ "${SPORTS_CLI_DRY_RUN:-0}" = 1 ]; then echo "[dry run] $*"; else "$@"; fi; }
has() { command -v "$1" >/dev/null 2>&1; }

case $(uname -s) in
  Darwin) OS=mac ;;
  Linux) OS=linux ;;
  *) fail 'Sports CLI runs on macOS and Linux. On Windows, install WSL (https://aka.ms/wsl) and run this command inside Ubuntu.' ;;
esac
has curl || fail 'curl is needed to download Sports CLI.'
has tar || fail 'tar is needed to unpack Sports CLI.'

# Homebrew lives outside the default PATH on Apple Silicon right after it is installed.
for prefix in /opt/homebrew /usr/local; do
  if [ -x "$prefix/bin/brew" ]; then eval "$("$prefix/bin/brew" shellenv)"; break; fi
done

good_python() { "$1" -c 'import curses, sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; }
find_python() {
  for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.9; do
    path=$(command -v "$candidate" 2>/dev/null) || continue
    # On a Mac without developer tools, /usr/bin/python3 is a stub that pops up an install dialog.
    if [ "$OS" = mac ] && [ "$path" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
    if good_python "$path"; then echo "$path"; return 0; fi
  done
  return 1
}
PYTHON=$(find_python || true)

needs=''
[ -n "$PYTHON" ] || needs="$needs Python,"
has mpv || needs="$needs mpv (the video player),"
if [ "$PPV" = 1 ]; then has node || needs="$needs Node.js (for PPV sources),"; fi
if [ "$OS" = mac ] && [ -n "$needs" ] && ! has brew; then needs=" Homebrew (the Mac package installer),$needs"; fi

say "Sports CLI will be installed in $APP and started with the command: sports"
if [ -n "$needs" ]; then echo "It will also install:${needs%,}."; fi
if [ "$OS" = linux ] && [ -n "$needs" ]; then echo 'Your password may be asked for to install those.'; fi
if [ "$YES" = 0 ] && [ -r /dev/tty ] && { : </dev/tty; } 2>/dev/null; then
  printf 'Press Enter to continue, or Ctrl-C to cancel. '
  read -r _ </dev/tty || true
fi

linux_install() {
  sudo=sudo; [ "$(id -u)" = 0 ] && sudo=
  if has apt-get; then run $sudo apt-get update && run $sudo apt-get install -y "$@"
  elif has dnf; then run $sudo dnf install -y "$@"
  elif has pacman; then run $sudo pacman -S --needed --noconfirm "$@"
  elif has zypper; then run $sudo zypper install -y "$@"
  else fail "install these with your package manager, then run this again: $*"
  fi
}

if [ "$OS" = mac ] && [ -n "$needs" ] && ! has brew; then
  say 'Installing Homebrew (it asks for your Mac password)'
  run /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/tty
  for prefix in /opt/homebrew /usr/local; do
    if [ -x "$prefix/bin/brew" ]; then eval "$("$prefix/bin/brew" shellenv)"; break; fi
  done
  has brew || [ "${SPORTS_CLI_DRY_RUN:-0}" = 1 ] || fail 'Homebrew did not finish installing. Run this command again.'
fi

if [ -z "$PYTHON" ]; then
  say 'Installing Python'
  if [ "$OS" = mac ]; then run brew install python; else linux_install python3; fi
  PYTHON=$(find_python || true)
  [ -n "$PYTHON" ] || [ "${SPORTS_CLI_DRY_RUN:-0}" = 1 ] || fail 'Python 3.9 or newer with curses could not be found after installing it.'
fi
if ! has mpv; then
  say 'Installing mpv'
  if [ "$OS" = mac ]; then run brew install mpv; else linux_install mpv; fi
fi
if [ "$PPV" = 1 ] && ! has node; then
  say 'Installing Node.js'
  if [ "$OS" = mac ]; then run brew install node; else linux_install nodejs npm git; fi
fi

say 'Downloading Sports CLI'
parent=$(dirname "$APP"); mkdir -p "$parent"
work=$(mktemp -d "$parent/.sports-cli-download.XXXXXX")
trap 'rm -rf "$work"' EXIT
case $ARCHIVE in
  http*) curl -fsSL "$ARCHIVE" -o "$work/app.tar.gz" ;;
  *) cp "$ARCHIVE" "$work/app.tar.gz" ;;
esac
mkdir "$work/app"
tar -xzf "$work/app.tar.gz" -C "$work/app" --strip-components=1
[ -f "$work/app/sports-cli" ] || fail 'the download did not contain Sports CLI.'
# Keep what earlier runs installed: the PPV resolver and the optional Python packages.
for kept in resolver .deps; do
  if [ -e "$APP/$kept" ]; then mv "$APP/$kept" "$work/app/$kept"; fi
done
rm -rf "$APP"; mv "$work/app" "$APP"

say 'Setting up optional packages'
if [ "$PPV" = 1 ] || has node; then
  PYTHON=$PYTHON SPORTS_CLI_INSTALLER=1 sh "$APP/setup.sh" || echo 'Some optional parts could not be set up; Sports CLI still works.'
else
  PYTHON=$PYTHON SPORTS_CLI_INSTALLER=1 SPORTS_CLI_SKIP_RESOLVER=1 sh "$APP/setup.sh" || echo 'Some optional parts could not be set up; Sports CLI still works.'
fi

mkdir -p "$BIN"
cat > "$BIN/sports" <<EOF
#!/bin/sh
# Sports CLI launcher written by install.sh.
case "\${1:-}" in
  --update) curl -fsSL https://raw.githubusercontent.com/$REPO/main/install.sh | sh -s -- --yes; exit ;;
  --setup) exec sh "$APP/install.sh" --yes ;;
  --setup-ppv) exec sh "$APP/install.sh" --yes --ppv ;;
esac
PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
SPORTS_CLI_COMMAND=sports
export PATH SPORTS_CLI_COMMAND
exec "$PYTHON" "$APP/sports-cli" "\$@"
EOF
chmod +x "$BIN/sports"

case :$PATH: in
  *:"$BIN":*) on_path=1 ;;
  *) on_path=0 ;;
esac
if [ "$on_path" = 0 ]; then
  line='export PATH="$HOME/.local/bin:$PATH"'
  for profile in "$HOME/.zprofile" "$HOME/.bash_profile" "$HOME/.profile"; do
    case $profile in
      */.zprofile) [ "$OS" = mac ] || [ -e "$profile" ] || continue ;;
      */.bash_profile) [ -e "$profile" ] || continue ;;
    esac
    grep -qsF "$line" "$profile" || printf '\n# Added by the Sports CLI installer\n%s\n' "$line" >> "$profile"
  done
fi

say 'Sports CLI is ready'
if [ "$on_path" = 1 ]; then echo 'Type: sports'; else echo 'Open a new Terminal window and type: sports'; fi
echo 'Later: "sports --update" updates it, and "sports --setup-ppv" adds PPV sources.'
