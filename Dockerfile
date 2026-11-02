FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends snmp && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/monitor
COPY app ./app
RUN useradd --uid 10001 --create-home monitor && mkdir /data && chown monitor:monitor /data
USER monitor
ENV MONITOR_DATA=/data
EXPOSE 8080
CMD ["python", "-m", "app.server"]
