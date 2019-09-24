with import <nixpkgs> {};
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

  gcc7_nolibc = wrapCCWith {
    cc = gcc7.cc;
    bintools = wrapBintoolsWith {
      bintools = binutils-unwrapped;
      libc = null;
    };
    extraBuildCommands = ''
      sed -i '2i if ! [[ $@ == *'musl-gcc.specs'* ]]; then exec ${gcc7}/bin/gcc -L${glibc}/lib -L${glibc.static}/lib "$@"; fi' \
        $out/bin/gcc

      sed -i '2i if ! [[ $@ == *'musl-gcc.specs'* ]]; then exec ${gcc7}/bin/g++ -L${glibc}/lib -L${glibc.static}/lib "$@"; fi' \
        $out/bin/g++

      sed -i '2i if ! [[ $@ == *'musl-gcc.spec'* ]]; then exec ${gcc7}/bin/cpp "$@"; fi' \
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

  kernel = linuxPackages_4_14.kernel;
in (overrideCC stdenv gcc7_nolibc).mkDerivation {
  name = "env";

  nativeBuildInputs = [
    git
    bear
    dockerctl
    tapctl
    docker
    jdk
    maven
    automake
    autoconf
    libtool
    pkgconfig
    flex
    bison
    bc
    gettext
    openssl
    (python3.withPackages(ps: [
      ps.pandas
      ps.seaborn
      (remote_pdb ps)
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

  # conditionally used by .envrc
  NIXOS_KERNELDIR = "${kernel.dev}/lib/modules/${kernel.modDirVersion}/build";

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
    libgcc
    json_c
    curl
    linuxHeaders
  ];

  SGXLKL_TAP = "sgxlkl_tap0";
  SGXLKL_IP4 = "10.218.101.1";
  #SGXLKL_GW4 = "10.218.101.254";
  SGXLKL_DPDK_MAC = "62:48:ed:5e:f7:d8";
  FSTEST_MNT = "/mnt/vdb";
  SGXLKL_TAP_OFFLOAD="1";
  SGXLKL_TAP_MTU="9000";

  shellHook = ''
    export DOCKER_HOST=unix://$PWD/.docker/docker.sock
  '';
}