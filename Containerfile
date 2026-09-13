FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36 AS build

ARG CFO_SOURCE_REVISION
WORKDIR /build
COPY . .
RUN python scripts/build_source_manifest.py --root . --revision "${CFO_SOURCE_REVISION}" \
    && python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

WORKDIR /app
COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels \
    && mkdir -p /data && chown 65532:65532 /data
COPY --from=build --chown=65532:65532 /build/.cfo-source.json /app/.cfo-source.json
COPY --from=build --chown=65532:65532 /build/counterfactual_ops /app/counterfactual_ops
COPY --from=build --chown=65532:65532 /build/examples /app/examples
COPY --from=build --chown=65532:65532 /build/evidence /app/evidence
USER 65532:65532
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
VOLUME ["/data"]
CMD ["python", "-m", "counterfactual_ops.hosted"]
