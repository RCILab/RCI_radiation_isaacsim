FROM nvcr.io/nvidia/isaac-sim:5.1.0

USER root

ENV ACCEPT_EULA=Y \
    PRIVACY_CONSENT=Y \
    PYTHONDONTWRITEBYTECODE=1 \
    RADIATION_WS=/workspace/radiation_isaacsim_ws

WORKDIR /workspace/radiation_isaacsim_ws

COPY . /workspace/radiation_isaacsim_ws
COPY docker/entrypoint.sh /opt/radiation/entrypoint.sh

RUN chmod +x /opt/radiation/entrypoint.sh

ENTRYPOINT ["/opt/radiation/entrypoint.sh"]
CMD ["bash"]
