FROM python:3-alpine

COPY . /beancount

RUN apk add --update --no-cache --virtual .build-deps libxml2-dev libxslt-dev build-base \
    && cd /beancount \
    && pip install . \
    && cp ./bin/* /usr/local/bin \
    && cd / \
    && rm -rf /beancount \
    && pip install fava \
    && apk del --no-cache .build-deps

ENV FAVA_HOST=0.0.0.0
VOLUME /data
WORKDIR /data

CMD ["fava", "master.bean"]
