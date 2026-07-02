# syntax=docker/dockerfile:1.7

FROM hub.oepkgs.net/openeuler/openeuler:24.03-lts-sp3 AS base

ARG USER_NAME=statebus
ARG USER_UID=1000
ARG USER_GID=1000
ARG STATEBUS_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG STATEBUS_TORCH_SPEC=torch==2.5.1
ARG STATEBUS_TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    PIP_ROOT_USER_ACTION=ignore \
    STATEBUS_CONTAINER_USER_NAME=${USER_NAME} \
    STATEBUS_CONTAINER_USER_UID=${USER_UID} \
    STATEBUS_CONTAINER_USER_GID=${USER_GID} \
    STATEBUS_DEFAULT_PIP_INDEX_URL=${STATEBUS_PIP_INDEX_URL} \
    STATEBUS_DEFAULT_TORCH_SPEC=${STATEBUS_TORCH_SPEC} \
    STATEBUS_DEFAULT_TORCH_INDEX_URL=${STATEBUS_TORCH_INDEX_URL}

RUN dnf install -y --setopt=install_weak_deps=False \
    bubblewrap \
    bash \
    coreutils \
    findutils \
    git \
    gcc \
    gcc-c++ \
    make \
    cmake \
    which \
    procps-ng \
    shadow-utils \
    tar \
    gzip \
    unzip \
    nodejs \
    npm \
    sqlite \
    sqlite-devel \
    python3 \
    python3-devel \
    python3-pip \
    && dnf clean all

RUN groupadd --gid ${STATEBUS_CONTAINER_USER_GID} ${STATEBUS_CONTAINER_USER_NAME} \
    && useradd --uid ${STATEBUS_CONTAINER_USER_UID} --gid ${STATEBUS_CONTAINER_USER_GID} -m ${STATEBUS_CONTAINER_USER_NAME}

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --upgrade \
    --prefer-binary \
    --index-url ${STATEBUS_DEFAULT_PIP_INDEX_URL} \
    pip setuptools wheel

WORKDIR /workspace/statebus/project

FROM base AS core-deps

COPY requirements-container-core.txt /tmp/statebus-requirements-container-core.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install \
    --prefer-binary \
    --index-url ${STATEBUS_DEFAULT_PIP_INDEX_URL} \
    -r /tmp/statebus-requirements-container-core.txt

FROM core-deps AS embed-deps

COPY requirements-container-embed.txt /tmp/statebus-requirements-container-embed.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install \
    --prefer-binary \
    --index-url ${STATEBUS_DEFAULT_TORCH_INDEX_URL} \
    --extra-index-url ${STATEBUS_DEFAULT_PIP_INDEX_URL} \
    ${STATEBUS_DEFAULT_TORCH_SPEC}

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install \
    --prefer-binary \
    --index-url ${STATEBUS_DEFAULT_PIP_INDEX_URL} \
    --extra-index-url ${STATEBUS_DEFAULT_TORCH_INDEX_URL} \
    -r /tmp/statebus-requirements-container-embed.txt

FROM core-deps AS core

RUN mkdir -p \
    /root/.local \
    /statebus/models \
    /statebus/caches \
    /statebus/logs \
    /statebus/runs \
    /statebus/work \
    /statebus/workspaces

COPY docker/entrypoint.sh /usr/local/bin/statebus-entrypoint.sh
RUN chmod +x /usr/local/bin/statebus-entrypoint.sh
COPY docker/activate_statebus_container.sh /usr/local/bin/activate_statebus_container.sh
RUN chmod +x /usr/local/bin/activate_statebus_container.sh
COPY scripts/setup_container_embed_stack.sh /usr/local/bin/statebus-setup-container-embed-stack.sh
RUN chmod +x /usr/local/bin/statebus-setup-container-embed-stack.sh
COPY scripts/setup_container_codex_cli.sh /usr/local/bin/statebus-setup-container-codex-cli.sh
RUN chmod +x /usr/local/bin/statebus-setup-container-codex-cli.sh

USER 0:0

ENTRYPOINT ["/usr/local/bin/statebus-entrypoint.sh"]
CMD ["bash"]

FROM embed-deps AS embed

RUN mkdir -p \
    /root/.local \
    /statebus/models \
    /statebus/caches \
    /statebus/logs \
    /statebus/runs \
    /statebus/work \
    /statebus/workspaces

COPY docker/entrypoint.sh /usr/local/bin/statebus-entrypoint.sh
RUN chmod +x /usr/local/bin/statebus-entrypoint.sh
COPY docker/activate_statebus_container.sh /usr/local/bin/activate_statebus_container.sh
RUN chmod +x /usr/local/bin/activate_statebus_container.sh
COPY scripts/setup_container_embed_stack.sh /usr/local/bin/statebus-setup-container-embed-stack.sh
RUN chmod +x /usr/local/bin/statebus-setup-container-embed-stack.sh
COPY scripts/setup_container_codex_cli.sh /usr/local/bin/statebus-setup-container-codex-cli.sh
RUN chmod +x /usr/local/bin/statebus-setup-container-codex-cli.sh

USER 0:0

ENTRYPOINT ["/usr/local/bin/statebus-entrypoint.sh"]
CMD ["bash"]
