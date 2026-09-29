# FGA Relay. Pure Python, so the same file builds for ARM and Intel with no compiling.
FROM python:3.12-alpine

RUN apk add --no-cache jq tzdata
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app /app/app
COPY run.sh /run.sh
RUN chmod +x /run.sh
CMD ["/run.sh"]
