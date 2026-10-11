# BoardRunner with everything it runs on: the patched QEMU, FastDyn (with the
# device models and passthrough), libhw and LibVIO, all built from source.
# The entry point runs the NUCLEO-F103RB evaluation
# (evaluation/nucleo_f103rb/run.sh); see evaluation/nucleo_f103rb/README.md.
#
# Before building, check out FastDyn and the submodules it builds from:
#   git -c protocol.file.allow=always submodule update --init deps/fastdyn
#   git -C deps/fastdyn submodule update --init --depth 1 \
#       third_party/common/qemu third_party/common/libhw \
#       third_party/common/cmsis-svd-data device_models/elder/inih
# LibVIO comes from its own checkout:
#   docker build --build-context libvio=/path/to/LibVIO -t boardrunner .

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config cmake ninja-build flex bison git ca-certificates \
        python3 python3-venv python3-pip \
        libglib2.0-dev libpixman-1-dev libfdt-dev libcjson-dev \
        libstlink-dev libusb-1.0-0-dev openocd \
        socat procps util-linux binutils \
    && rm -rf /var/lib/apt/lists/*

# LibVIO, installed to /usr/local (found through pkg-config vio)
COPY --from=libvio . /src/libvio
RUN cmake -S /src/libvio -B /src/libvio/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /src/libvio/build -j"$(nproc)" \
    && cmake --install /src/libvio/build --prefix /usr/local \
    && ldconfig && rm -rf /src/libvio

COPY deps/fastdyn /opt/boardrunner/deps/fastdyn
WORKDIR /opt/boardrunner/deps/fastdyn

# Python: FastDyn's requirements (meson among them) and FastDyn
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
RUN python3 -m venv /opt/venv \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e src

# The patched QEMU FastDyn runs in (FastDyn's patch applied to the pinned submodule)
RUN cd third_party/common/qemu && P=../../../patches/qemu-fastdyn-plugin-icount.patch \
    && { patch -p1 -R -s -f --dry-run < $P >/dev/null || patch -p1 < $P; } \
    && mkdir build && cd build \
    && ../configure --target-list=arm-softmmu --enable-plugins \
    && make -j"$(nproc)" qemu-system-arm

# libhw (passthrough to the board) and FastDyn
RUN make -C third_party/common/libhw \
    && meson setup build \
        -Dqemu_path="$PWD/third_party/common/qemu" \
        -Dlibhw_path="$PWD/third_party/common/libhw" \
        -Ddevice_models=true -Denable_libhw=true -DDEBUG_PRINT=true \
    && ninja -C build

# BoardRunner (installed after FastDyn, so `boardrunner` is BoardRunner's command)
WORKDIR /opt/boardrunner
COPY pyproject.toml README.md ./
COPY boardrunner boardrunner
COPY evaluation evaluation
COPY examples examples
COPY tests tests
RUN pip install --no-cache-dir -e . \
    && boardrunner --version && fastdyn --help >/dev/null

ENTRYPOINT ["/opt/boardrunner/evaluation/nucleo_f103rb/run.sh"]
CMD ["help"]
