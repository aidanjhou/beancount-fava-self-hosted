FROM python:3.12-slim

# Set default environment variables for Fava
ENV FAVA_HOST="0.0.0.0" \
    FAVA_PORT="8000" \
    BEANCOUNT_FILE="/data/main.beancount"

WORKDIR /data

# Install fava with optional excel export support
RUN pip install --no-cache-dir --root-user-action ignore "fava[excel]"

# Default data mount directory
VOLUME ["/data"]

EXPOSE 8000

# Copy entrypoint script
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["fava"]
