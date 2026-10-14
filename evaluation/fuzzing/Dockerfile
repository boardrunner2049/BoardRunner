# The Table 8 campaigns from this repository: the patched QEMU, FastDyn built
# with AFLNet (its basic-block collector is also what the baselines use),
# libhw, LibVIO, AFLNet and BoardRunner, all built from source.
#
# Build from the repository root, after checking out FastDyn and the
# submodules it builds from (as for the main Dockerfile):
#   git submodule update --init deps/fastdyn
#   git -C deps/fastdyn submodule update --init --depth 1 \
#       third_party/common/qemu third_party/common/libhw \
#       third_party/common/cmsis-svd-data
#   docker build -f evaluation/fuzzing/Dockerfile \
#       --build-context libvio=/path/to/LibVIO -t boardrunner-fuzzing .
#
# Run a launcher with a host directory for the results (README.md):
#   docker run --rm -v "$PWD/results:/results" boardrunner-fuzzing \
#       evaluation/fuzzing/scripts/run_qemu_coverage.sh all --work-dir /results/qemu

FROM ubuntu:24.04

ARG AFLNET_REPOSITORY=https://github.com/CSmith1539/aflnet.git
ARG AFLNET_COMMIT=509a10384d53ce6dd6f04c6870454619dbf7d35e

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config cmake ninja-build flex bison git ca-certificates \
        python3 python3-venv python3-pip \
        libglib2.0-dev libpixman-1-dev libfdt-dev libcjson-dev \
        libstlink-dev libusb-1.0-0-dev openocd \
        libcap-dev libgraphviz-dev \
        socat procps util-linux binutils dosfstools iproute2 iputils-ping \
        netcat-openbsd curl mosquitto mosquitto-clients \
    && rm -rf /var/lib/apt/lists/*

# LibVIO, installed to /usr/local (found through pkg-config vio)
COPY --from=libvio . /src/libvio
RUN cmake -S /src/libvio -B /src/libvio/build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /src/libvio/build -j"$(nproc)" \
    && cmake --install /src/libvio/build --prefix /usr/local \
    && ldconfig && rm -rf /src/libvio

# AFLNet (the fork with FastDyn's in-process entry point), pinned
RUN git init /opt/aflnet \
    && git -C /opt/aflnet remote add origin "$AFLNET_REPOSITORY" \
    && git -C /opt/aflnet fetch --depth 1 origin "$AFLNET_COMMIT" \
    && git -C /opt/aflnet checkout --detach FETCH_HEAD \
    && make -C /opt/aflnet -j"$(nproc)" afl-fuzz libaflnet.a

COPY deps/fastdyn /opt/boardrunner/deps/fastdyn
WORKDIR /opt/boardrunner/deps/fastdyn

# Python: FastDyn's requirements (meson among them), FastDyn, and the Modbus
# master the Modbus baseline uses
ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
RUN python3 -m venv /opt/venv \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -e src \
    && pip install --no-cache-dir 'pymodbus>=3.0' pyserial

# The patched QEMU FastDyn runs in (FastDyn's patch applied to the pinned submodule)
RUN cd third_party/common/qemu && P=../../../patches/qemu-fastdyn-plugin-icount.patch \
    && { patch -p1 -R -s -f --dry-run < $P >/dev/null || patch -p1 < $P; } \
    && mkdir build && cd build \
    && ../configure --target-list=arm-softmmu --enable-plugins \
    && make -j"$(nproc)" qemu-system-arm

# libhw (passthrough to the board) and FastDyn with AFLNet
RUN make -C third_party/common/libhw \
    && meson setup build \
        -Dqemu_path="$PWD/third_party/common/qemu" \
        -Dlibhw_path="$PWD/third_party/common/libhw" \
        -Daflnet_path=/opt/aflnet \
        -Ddevice_models=true -Denable_libhw=true -Denable_aflnet=true -DDEBUG_PRINT=true \
    && ninja -C build \
    && nm -D build/libfastdyn.so | grep -q ' T fuzz_bbl_init'

# BoardRunner (installed after FastDyn, so `boardrunner` is BoardRunner's command)
WORKDIR /opt/boardrunner
COPY pyproject.toml README.md ./
COPY boardrunner boardrunner
COPY evaluation evaluation
COPY examples examples
RUN pip install --no-cache-dir -e . \
    && boardrunner --version && fastdyn --help >/dev/null

CMD ["bash"]
