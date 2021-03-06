with import (builtins.fetchTarball {
  url = "https://github.com/NixOS/nixpkgs/archive/92c884dfd7140a6c3e6c717cf8990f7a78524331.tar.gz";
  sha256 = "sha256:0wk2jg2q5q31wcynknrp9v4wc4pj3iz3k7qlxvfh7gkpd8vq33aa";
}) {};
let
  tapctl = pkgs.writeScriptBin "tapctl" ''
    #!${pkgs.runtimeShell}
    set -eu -o pipefail
    INTERFACE=sgxlkl_tap0
    case "''${1:-}" in
    start)
      ip tuntap add dev "$INTERFACE" mode tap user ''${SUDO_UID:-docker}
      ip link set dev "$INTERFACE" up
      ip addr add dev "$INTERFACE" 10.218.101.254/24
      ;;
    stop)
      ip tuntap del dev "$INTERFACE" mode tap
      ;;
    status)
      ip addr show dev "$INTERFACE"
      ;;
    *)
      echo "USAGE: $0 start|stop|status"
      exit 1
      ;;
    esac
  '';
  dockerctl = pkgs.writeScriptBin "dockerctl" ''
    #!${pkgs.runtimeShell}
    set -eu -o pipefail
    DIR="$PWD/.docker"
    DATAROOT="$PWD/.docker/data"
    LOG="$DIR/docker.log"
    PIDFILE="$DIR/docker.pid"

    if [ ! -x "$PWD/sgx-lkl-docker.sh" ]; then
      echo "This command must be executed from the project root" 2>&1
      exit 1
    fi

    stop-docker() {
      if [[ ! -f "$PIDFILE" ]]; then
        echo "No pid file at $PIDFILE, is docker running?" 2>&1
        exit 1
      fi
      kill "$(cat $PIDFILE)"
    }

    case "''${1:-}" in
    start)
      mkdir -p -m755 "$DIR"
      echo "log to $LOG"
      ${pkgs.docker}/bin/dockerd \
        --pidfile "$PIDFILE" \
        --host "unix://$DIR/docker.sock" \
        --group "''${SUDO_GID:-docker}" \
        --data-root "$DATAROOT" 2>> "$LOG" &
      tail "$LOG"
      ;;
    stop)
      stop-docker
      ;;
    purge)
      stop-docker
      rm -rf "$DATAROOT"
      ;;
    status)
      if [[ ! -f "$PIDFILE" ]] || ! kill -0 "$(cat $PIDFILE)"; then
        echo -e "docker is stopped\n"
      else
        echo -e "docker is running\n"
      fi
      tail "$LOG"
      ;;
    *)
      echo "USAGE: $0 start|stop|status" 2>&1
      exit 1
      ;;
    esac
  '';

  gcc_nolibc = wrapCCWith {
    cc = gcc9.cc;
    bintools = wrapBintoolsWith {
      bintools = binutils-unwrapped;
      libc = null;
    };
    extraBuildCommands = ''
      sed -i '2i if ! [[ $@ == *'musl-gcc.specs'* ]]; then exec ${gcc9}/bin/gcc -L${glibc}/lib -L${glibc.static}/lib "$@"; fi' \
        $out/bin/gcc

      sed -i '2i if ! [[ $@ == *'musl-gcc.specs'* ]]; then exec ${gcc9}/bin/g++ -L${glibc}/lib -L${glibc.static}/lib "$@"; fi' \
        $out/bin/g++

      sed -i '2i if ! [[ $@ == *'musl-gcc.spec'* ]]; then exec ${gcc9}/bin/cpp "$@"; fi' \
        $out/bin/cpp
    '';
  };

  remote_pdb = ps: ps.buildPythonPackage rec {
    pname = "remote-pdb";
    version = "1.3.0";
    src = ps.fetchPypi {
      inherit pname version;
      sha256 = "0gqz1j8gkrvb4vws0164ac75cbmjk3lj0jljrv0igpblgvgdshg4";
    };
  };

in (overrideCC stdenv gcc_nolibc).mkDerivation {
  name = "env";

  hardeningDisable = [ "all" ];

  nativeBuildInputs = [
    git
    bear
    dockerctl
    cryptsetup
    tapctl
    docker
    automake
    autoconf
    libtool
    hostname
    pkgconfig
    flex
    bison
    bc
    perl
    gettext
    (lib.getBin glibc)
    openssl
    python3.pkgs.pandas
    python3.pkgs.ipdb
    (python3.withPackages(ps: [
      ps.pandas
      ps.seaborn
      (remote_pdb ps)
      ps.capstone
    ]))
    which
    wget
    pciutils
    utillinux
    kmod
    e2fsprogs
    iproute
    openssh
    procps
    rsync
    protobufc
    protobuf
  ];
  # this might need to adapt to the actual CPU. this works well on i9-9900K CPU @ 3.60GHz
  OPENSSL_ia32cap = "0x5640020247880000:0x40128";

  buildInputs = [
    #(cryptsetup.overrideAttrs (old: {
    #  buildInputs = (old.buildInputs or []) ++ [
    #    glibc.out glibc.static
    #  ];
    #  NIX_LDFLAGS = ""; # -lgcc breaks static linking
    #  configureFlags = (old.configureFlags or []) ++ [ "--enable-static" ];
    #}))
    protobuf
    libgcrypt
    json_c
    curl
  ];

  LINUX_HEADERS_INC = "${linuxHeaders}/include";

  SGXLKL_TAP = "sgxlkl_tap0";

  SGXLKL_IP4 = "10.218.101.1";
  #SGXLKL_GW4 = "10.218.101.254";

  SGXLKL_DPDK_MAC = "62:48:ed:5e:f7:d8";
  FSTEST_MNT = "/mnt/vdb";
  SGXLKL_TAP_OFFLOAD="1";
  SGXLKL_TAP_MTU="9000";
  SGXLKL_KERNEL_VERBOSE = 1;
  SGXLKL_VERBOSE = 1;
  SCONE_HEAP = "4G";
  SCONE_CONFIG = toString ./apps/nix/scone/sgx-musl.conf;

  shellHook = ''
    export DOCKER_HOST=unix://$PWD/.docker/docker.sock
    export PATH=$PATH:$(realpath build)
  '';
}
