FROM python:3.7-alpine

RUN apk update && apk add git

RUN mkdir /app
WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

CMD flask run --host=0.0.0.0 --port=5000
