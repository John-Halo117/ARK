package config

import (
	"os"
	"strconv"
	"time"
)

type RuntimeConfig struct {
	HTTPAddr          string
	RedisAddr         string
	NATSURL           string
	ReadHeaderTimeout time.Duration
	GMax              float64
	SigmaK            float64
	HysteresisLambda  float64
	BackpressureEps   float64
	TimeDecayRate     float64
	ServiceName       string
	ConnectivityMode  string
	AllowExternal     bool
	APIToken          string
}

func LoadRuntimeConfig(defaultAddr string) RuntimeConfig {
	return RuntimeConfig{
		HTTPAddr:          envOr("HTTP_ADDR", defaultAddr),
		RedisAddr:         envOr("REDIS_ADDR", "redis:6379"),
		NATSURL:           envOr("NATS_URL", "nats://nats:4222"),
		ReadHeaderTimeout: envDurationOr("HTTP_READ_HEADER_TIMEOUT", 5*time.Second),
		GMax:              envFloatOr("G_MAX", 0.8),
		SigmaK:            envFloatOr("SIGMA_K", 2.2),
		HysteresisLambda:  envFloatOr("HYSTERESIS_LAMBDA", 0.08),
		BackpressureEps:   envFloatOr("BACKPRESSURE_EPS", 0.1),
		TimeDecayRate:     envFloatOr("TIME_DECAY_RATE", 0.2),
		ServiceName:       envOr("ARK_SERVICE_NAME", "ark-service"),
		ConnectivityMode:  envOr("ARK_CONNECTIVITY_MODE", "offline"),
		AllowExternal:     envBoolOr("ARK_ALLOW_EXTERNAL", false),
		APIToken:          envOr("ARK_API_TOKEN", ""),
	}
}

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func envFloatOr(k string, d float64) float64 {
	if v := os.Getenv(k); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return d
}

func envDurationOr(k string, d time.Duration) time.Duration {
	if v := os.Getenv(k); v != "" {
		if t, err := time.ParseDuration(v); err == nil {
			return t
		}
	}
	return d
}

func envBoolOr(k string, d bool) bool {
	if v := os.Getenv(k); v != "" {
		return v == "1" || v == "true" || v == "TRUE"
	}
	return d
}
