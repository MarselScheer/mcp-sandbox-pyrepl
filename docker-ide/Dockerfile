ARG BASE_IMAGE=
FROM ${BASE_IMAGE}

ARG USER_ID=
ARG GROUP_ID=

# RUN groupadd -g ${GROUP_ID} ide \
#     && useradd -l ide -u ${USER_ID} --create-home -g ${GROUP_ID} \
RUN apt-get update -yqq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    git \
    ssh \
    curl \
    emacs \
    npm \
    zip \
    fonts-symbola \
    fonts-noto-color-emoji

RUN npm install -g @fission-ai/openspec@1.4.1

USER ubuntu
WORKDIR /home/ubuntu

ENV PATH="/home/ubuntu/.local/bin:${PATH}"
RUN curl -LsSf https://astral.sh/uv/0.11.29/install.sh | sh \
  && uv tool install --exclude-newer="30 days" trafilatura

COPY --chown=${USER_ID}:${GROUP_ID} --chmod=744 ./entrypoint.sh /
RUN git config --global user.email "scheer@freescience.de" \
    && git config --global user.name "Marsel Scheer" \
    && mkdir -p .emacs.d/eshell \
    && echo "alias e rm -rf .emacs.d && ln -s repos/mcp-sandbox-pyrepl/emacs-from-scratch .emacs.d" >> .emacs.d/eshell/alias
ENTRYPOINT ["/entrypoint.sh"]


