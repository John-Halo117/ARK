FROM golang:1.24-alpine AS build

ARG SERVICE_PATH=./cmd/ingestion-leader

WORKDIR /src

COPY go.mod ./
RUN go mod download

COPY cmd ./cmd
COPY internal ./internal

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o /out/service ${SERVICE_PATH}

FROM alpine:3.20

RUN apk add --no-cache ca-certificates

COPY --from=build /out/service /service

ENTRYPOINT ["/service"]
